"""POST /imports/combined-export over HTTP."""

import csv
import io

from openpyxl import load_workbook

from .test_api import make_client, upload
from .test_api_export import approved_import, csv_rows

URL = "/imports/combined-export"


def two_files(client):
    a = approved_import(client)
    state = upload(client, supplier="Beta SA").json()
    session_id = state["id"]
    for question in state["questions"]:
        answer = {"number_format": "decimal_comma", "price_includes_vat": "yes", "currency": "ARS"}[question["id"]]
        client.post(f"/imports/{session_id}/answers", json={"question_id": question["id"], "option": answer})
    assert client.post(f"/imports/{session_id}/approve").status_code == 200
    return a, session_id


def test_products_csv_over_http_with_headers_and_supplier_column():
    client = make_client()
    a, b = two_files(client)
    response = client.post(URL, json={"session_ids": [b, a], "format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="pricor-combined-2-files-products.csv"'
    rows = csv_rows(response)
    single = csv_rows(client.get(f"/imports/{a}/export"))
    assert rows[0] == ["supplier", *single[0]]
    assert [r[0] for r in rows[1:]] == ["Beta SA"] * 5 + ["Ferreteria Ejemplo"] * 5
    assert [r[1:] for r in rows[6:]] == single[1:]


def test_rejected_xlsx_over_http_and_kind_default_is_products():
    client = make_client()
    a, b = two_files(client)
    response = client.post(URL, json={"session_ids": [a, b], "format": "xlsx", "kind": "rejected"})
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="pricor-combined-2-files-rejected.xlsx"'
    sheet = load_workbook(io.BytesIO(response.content))["Rejected rows"]
    assert sheet["A1"].value == "supplier" and sheet["A2"].value == "Ferreteria Ejemplo"
    default = client.post(URL, json={"session_ids": [a], "format": "csv"})
    assert "products.csv" in default.headers["content-disposition"]


def test_error_statuses():
    client = make_client()
    a = approved_import(client)
    pending = upload(client).json()["id"]
    cases = [
        ({"session_ids": [a, "nope"], "format": "csv"}, 404, "session_not_found"),
        ({"session_ids": [a, pending], "format": "csv"}, 409, "invalid_operation"),
        ({"session_ids": [], "format": "csv"}, 422, "invalid_input"),
        ({"session_ids": [a, a], "format": "csv"}, 422, "invalid_input"),
        ({"session_ids": [f"x{i}" for i in range(51)], "format": "csv"}, 422, "invalid_input"),
        ({"session_ids": [a], "format": "pdf"}, 422, "invalid_input"),
        ({"session_ids": [a], "format": "csv", "kind": "x"}, 422, "invalid_input"),
    ]
    for body, status, code in cases:
        response = client.post(URL, json=body)
        assert (response.status_code, response.json()["error"]["code"]) == (status, code), body


def test_single_session_exports_are_unchanged():
    client = make_client()
    a, _ = two_files(client)
    before = client.get(f"/imports/{a}/export").content
    client.post(URL, json={"session_ids": [a], "format": "csv"})
    assert client.get(f"/imports/{a}/export").content == before
    assert csv_rows(client.get(f"/imports/{a}/export"))[0][0] == "supplier_code"


def test_custom_frozen_formats_over_http_and_conflict_on_difference():
    from fastapi.testclient import TestClient

    from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
    from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
    from pricor.adapters.sqlite_store import SqliteDatabase
    from pricor.application.manage_output_format import ManageOutputFormat
    from pricor.entrypoints.api import ApiDependencies, create_app

    from ..persistence.sessions import Flow

    db = SqliteDatabase(":memory:")
    try:
        manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
        first = Flow(output_formats=db.output_format)
        client = TestClient(create_app(ApiDependencies(first.use_case, output_format=manager)))
        manager.define([("SKU", "field:supplier_code", None, "code")])
        a = first.approved().id
        b = Flow(repository=first.repository, supplier="Beta", output_formats=db.output_format).approved().id
        ok = client.post(URL, json={"session_ids": [a, b], "format": "csv"})
        rows = list(csv.reader(io.StringIO(ok.content.decode("utf-8-sig"))))
        assert rows[0] == ["supplier", "SKU"] and rows[1][0] == "Ferreteria Ejemplo"
        manager.define([("Otro", "field:description", None)])
        c = Flow(repository=first.repository, supplier="Gamma", output_formats=db.output_format).approved().id
        clash = client.post(URL, json={"session_ids": [a, c], "format": "csv"})
        assert clash.status_code == 409 and clash.json()["error"]["code"] == "invalid_operation"
        assert "different output formats" in clash.json()["error"]["message"]
    finally:
        db.close()
