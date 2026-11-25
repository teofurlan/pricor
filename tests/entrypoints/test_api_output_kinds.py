import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.pdf_table_reader import PdfTableReader
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.entrypoints.api import ApiDependencies, create_app
from pricor.ports.output_format import OutputProposal

from ..adapters.pdf_fixtures import pdf_bytes
from ..persistence.sessions import Flow


class Scripted:
    """The AI's own mapping: header -> (source, confidence)."""

    def __init__(self, mapping):
        self.mapping = mapping

    def propose(self, columns):
        return tuple(OutputProposal(*self.mapping.get(c.name, ("empty", 0.0))[:1], "gemma", self.mapping.get(c.name, ("empty", 0.0))[1]) for c in columns)


def make(proposer=None):
    db = SqliteDatabase(":memory:")
    flow = Flow()
    manager = ManageOutputFormat(
        FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat(), proposer,
        pdf_reader=PdfTableReader(),
    )
    return TestClient(create_app(ApiDependencies(flow.use_case, output_format=manager))), flow, db


@pytest.fixture
def api():
    client, flow, db = make()
    yield client, flow
    db.close()


def upload_csv(client, header, name="t.csv"):
    return client.post("/output-format", files={"file": (name, (",".join(header) + "\n" + ",".join("x" for _ in header) + "\n").encode())})


# -- kind --

def test_uploaded_columns_get_the_default_kind_of_their_proposal(api):
    client, _ = api
    body = upload_csv(client, ["SKU", "Descripcion", "Costo", "IVA", "Moneda", "Otro"]).json()
    assert [c["kind"] for c in body["columns"]] == ["code", "description", "price", "number", "text", "text"]
    assert client.get("/output-format").json() == body


def test_put_accepts_kind_and_defaults_it_from_the_source(api):
    client, _ = api
    response = client.put("/output-format", json={"columns": [
        {"name": "A", "source": "field:unit_cost_net", "kind": "text"},
        {"name": "B", "source": "field:unit_cost_net"},
        {"name": "C", "source": "field:unit_cost_net", "kind": None},
        {"name": "D", "source": "constant:12,5", "kind": "number"},
        {"name": "E", "source": "empty", "kind": "description"},
    ]})
    assert response.status_code == 200
    assert [c["kind"] for c in response.json()["columns"]] == ["text", "price", "price", "number", "description"]
    assert client.get("/output-format").json() == response.json()


@pytest.mark.parametrize("column", [
    {"name": "A", "source": "empty", "kind": "money"},
    {"name": "A", "source": "empty", "kind": 3},
    {"name": "A", "source": "constant:abc", "kind": "number"},
    {"name": "A", "source": "constant:abc", "kind": "price"},
    {"name": "A", "source": "constant:1.234,5", "kind": "price"},
    {"name": "A", "source": "constant:1e5", "kind": "number"},
])
def test_put_rejects_invalid_kind_or_constant_and_keeps_the_prior_format(api, column):
    client, _ = api
    before = upload_csv(client, ["SKU"]).json()
    response = client.put("/output-format", json={"columns": [column]})
    assert response.status_code == 422
    assert client.get("/output-format").json() == before


def test_text_constants_are_not_parsed(api):
    client, _ = api
    response = client.put("/output-format", json={"columns": [{"name": "A", "source": "constant:abc", "kind": "text"}]})
    assert response.status_code == 200


def test_kinds_shape_the_downloaded_products_file(api):
    client, flow = api
    client.put("/output-format", json={"columns": [
        {"name": "Codigo", "source": "field:supplier_code", "kind": "code"},
        {"name": "Costo", "source": "field:unit_cost_net", "kind": "price"},
        {"name": "Fijo", "source": "constant:7,5", "kind": "number"},
    ]})
    session = flow.approved()
    csv = client.get(f"/imports/{session.id}/export").content.decode("utf-8-sig").splitlines()
    assert csv[0] == "Codigo,Costo,Fijo"
    assert csv[1].split(",")[2] == "7.5"
    sheet = load_workbook(io.BytesIO(client.get(f"/imports/{session.id}/export?format=xlsx").content))["Products"]
    row = list(sheet)[1]
    assert (row[0].number_format, row[1].number_format) == ("@", "0.00")


# -- fit --

def fit_of(proposals, state="proposed"):
    client, _, db = make(Scripted(proposals))
    try:
        header = list(proposals)
        body = upload_csv(client, header).json()
        if state == "confirmed":
            body = client.put("/output-format/mapping", json={"sources": ["empty"] * len(header)}).json()
        assert client.get("/output-format").json()["fit"] == body["fit"]
        return body["fit"]
    finally:
        db.close()


def test_fit_body_shape_and_unmatched_names():
    fit = fit_of({"SKU": ("field:supplier_code", 0.9), "Foto": ("empty", 0.0), "Nota": ("constant:x", 0.99)})
    assert fit == {"matched": 1, "total": 3, "unmatched": ["Foto", "Nota"], "mismatch": True}


@pytest.mark.parametrize("matched,total,mismatch", [
    (1, 1, True), (2, 2, False), (1, 2, True), (1, 3, True), (2, 3, False),
    (1, 4, True), (2, 4, False), (2, 5, True), (3, 5, False), (0, 6, True), (3, 6, False), (3, 7, True), (4, 7, False),
])
def test_mismatch_threshold_boundaries(matched, total, mismatch):
    proposals = {f"c{i}": ("field:description" if i < matched else "empty", 0.9) for i in range(total)}
    fit = fit_of(proposals)
    assert (fit["matched"], fit["total"], fit["mismatch"]) == (matched, total, mismatch)


def test_confidence_threshold_is_inclusive_at_half():
    fit = fit_of({"a": ("field:description", 0.5), "b": ("field:supplier_code", 0.4999)})
    assert (fit["matched"], fit["unmatched"]) == (1, ["b"])


def test_mismatch_is_never_raised_for_a_confirmed_format():
    fit = fit_of({"a": ("empty", 0.0), "b": ("empty", 0.0), "c": ("empty", 0.0)}, state="confirmed")
    assert (fit["matched"], fit["total"], fit["mismatch"]) == (0, 3, False)


def test_put_response_carries_fit(api):
    client, _ = api
    body = client.put("/output-format", json={"columns": [
        {"name": "A", "source": "field:description"}, {"name": "B", "source": "constant:x"}]}).json()
    assert body["fit"] == {"matched": 1, "total": 2, "unmatched": ["B"], "mismatch": False}


# -- PDF --

def test_pdf_template_proposes_the_first_table_headers(api):
    client, _ = api
    content = pdf_bytes([[["Codigo", "Detalle", "Costo"], ["001", "Tornillo", "10,50"]]])
    response = client.post("/output-format", files={"file": ("lista.pdf", content)})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "lista.pdf"
    assert [c["name"] for c in body["columns"]] == ["Codigo", "Detalle", "Costo"]
    assert body["columns"][0]["samples"] == ["001"] or body["columns"][0]["samples"] == []


def test_pdf_without_a_table_is_422_and_keeps_the_prior_format(api):
    client, _ = api
    before = upload_csv(client, ["SKU"]).json()
    response = client.post("/output-format", files={"file": ("x.pdf", pdf_bytes([["no table here"]]))})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unreadable_file"
    assert client.get("/output-format").json() == before


def test_pdf_is_accepted_on_price_list_endpoints_and_txt_is_rejected(api):
    client, _ = api
    content = pdf_bytes([[["Codigo", "Costo"], ["1", "2"]]])
    imports = client.post("/imports", files={"file": ("lista.pdf", content)}, data={"supplier_name": "X"})
    assert imports.status_code == 201
    assert client.post("/sheets", files={"file": ("lista.pdf", content)}).status_code == 200
    assert client.post("/imports", files={"file": ("lista.txt", b"hello")}, data={"supplier_name": "X"}).status_code == 415
