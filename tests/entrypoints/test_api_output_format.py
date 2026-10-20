import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.entrypoints.wiring import dependencies_from_env
from pricor.ports.output_format import OUTPUT_FIELDS

from ..persistence.sessions import Flow


@pytest.fixture
def api():
    db = SqliteDatabase(":memory:")
    flow = Flow()
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    client = TestClient(create_app(ApiDependencies(flow.use_case, output_format=manager)))
    yield client, flow
    db.close()


def upload(client, filename="template.csv", content=b"SKU,Note\n001,example\n", **data):
    return client.post("/output-format", files={"file": (filename, content)}, data=data)


def test_wire_contract_upload_get_confirm_delete_and_export(api):
    client, flow = api
    assert client.get("/output-format").status_code == 404
    missing = client.put("/output-format/mapping", json={"sources": ["empty"]})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "output_format_not_found"
    response = upload(client)
    assert response.status_code == 201
    expected = {"name": "template.csv", "state": "proposed", "fields": list(OUTPUT_FIELDS), "columns": [
        {"index": 0, "name": "SKU", "samples": ["001"], "proposal": {"source": "field:supplier_code", "proposed_by": "heuristics", "confidence": 0.9}, "source": None},
        {"index": 1, "name": "Note", "samples": ["example"], "proposal": {"source": "empty", "proposed_by": "heuristics", "confidence": 0.0}, "source": None},
    ]}
    assert response.json() == expected
    assert client.get("/output-format").json() == expected
    session = flow.approved()
    assert client.get(f"/imports/{session.id}/export").content.startswith(b"\xef\xbb\xbfsupplier_code,")
    response = client.put("/output-format/mapping", json={"sources": ["field:supplier_code", "constant:001"]})
    assert response.status_code == 200
    expected["state"] = "confirmed"
    expected["columns"][0]["source"] = "field:supplier_code"
    expected["columns"][1]["source"] = "constant:001"
    assert response.json() == expected == client.get("/output-format").json()
    assert client.get(f"/imports/{session.id}/export").content.startswith(b"\xef\xbb\xbfSKU,Note\r\n")
    replacement = upload(client, "next.csv", b"Other\nvalue\n")
    assert replacement.status_code == 201
    assert replacement.json()["state"] == "proposed"
    assert replacement.json()["columns"][0]["source"] is None
    assert client.get(f"/imports/{session.id}/export").content.startswith(b"\xef\xbb\xbfsupplier_code,")
    assert client.delete("/output-format").status_code == 204
    assert client.get("/output-format").status_code == 404


@pytest.mark.parametrize("sources", [[], ["empty"], ["empty"] * 3,
    ["field:unknown", "empty"], ["constant:", "empty"],
    ["constant:" + "x" * 201, "empty"], ["constant:  ", "empty"],
    ["field:description", None], [5, "empty"],
])
def test_put_422_keeps_prior_format_unchanged(api, sources):
    client, _ = api
    before = upload(client).json()
    response = client.put("/output-format/mapping", json={"sources": sources})
    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert client.get("/output-format").json() == before


@pytest.mark.parametrize("filename,content", [("empty.csv", b"\n,,\n"), ("empty.csv", b"")])
def test_empty_upload_422_does_not_replace_format(api, filename, content):
    client, _ = api
    before = upload(client).json()
    response = upload(client, filename, content)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_file"
    assert client.get("/output-format").json() == before


def test_xlsx_upload_sheet_and_blank_header(api):
    client, _ = api
    book = Workbook()
    book.active.append(["Wrong"])
    chosen = book.create_sheet("Chosen")
    chosen.append([None, None])
    chosen.append(["Code", None])
    chosen.append(["001", "text"])
    buffer = io.BytesIO()
    book.save(buffer)
    response = upload(client, "template.xlsx", buffer.getvalue(), sheet="Chosen")
    assert response.status_code == 201
    assert [(c["name"], c["samples"]) for c in response.json()["columns"]] == [("Code", ["001"]), ("Column 2", ["text"])]


def test_real_wiring_supplies_persistent_manager(tmp_path):
    dependencies = dependencies_from_env({"PRICOR_DB": str(tmp_path / "wired.db")})
    assert isinstance(dependencies.output_format, ManageOutputFormat)
    client = TestClient(create_app(dependencies))
    # Avoid a live model call in this wiring test; manager fallbacks are covered separately.
    assert client.get("/output-format").status_code == 404


def test_hand_defined_columns_shape_the_products_file(api):
    client, flow = api
    response = client.put("/output-format", json={"columns": [
        {"name": "Nota", "source": "constant:x"},
        {"name": "SKU", "source": "field:supplier_code", "template_index": None},
    ]})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "confirmed" and body["name"] == ""
    assert [(c["name"], c["source"]) for c in body["columns"]] == [("Nota", "constant:x"), ("SKU", "field:supplier_code")]
    session = flow.approved()
    assert client.get(f"/imports/{session.id}/export").content.startswith(b"\xef\xbb\xbfNota,SKU\r\n")
    refused = client.put("/output-format", json={"columns": [{"name": "A", "source": "empty"}, {"name": "a", "source": "empty"}]})
    assert refused.status_code == 422
    assert client.get("/output-format").json() == body
    assert client.put("/output-format", json={"columns": [{"name": "A", "source": "empty", "x": 1}]}).status_code == 422
