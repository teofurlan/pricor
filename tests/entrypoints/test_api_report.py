import csv
import io

import pytest
from fastapi.testclient import TestClient

from pricor.adapters.report_csv_exporter import ReportCsvExporter
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.cascade import ClassifierStage
from pricor.application.report_price_changes import ReportPriceChanges
from pricor.application.reuse_supplier_plan import ReuseSupplierPlan
from pricor.entrypoints.api import ApiDependencies, create_app

from ..application.fakes import FakeClassifier
from .test_api import ROLES, ROWS, answer, upload

FIRST = [row for row in ROWS if row[0] not in ("LISTA OCTUBRE", "TOTAL", "", "A6")]
SECOND = [
    ["Codigo", "Descripcion", "Precio lista", "IVA"],
    ["A1", "Tornillo", "1.331,00", "21%"],  # +10%
    ["A2", "Tuerca", "2.904,00", "21%"],  # +200%: an anomaly
    ["A4", "Clavo", "60,50", "21%"],  # unchanged
    ["A5", "Taco", "1.089,00", "21%"],  # -40%: an anomaly
    ["A7", "Brida", "100,00", "21%"],  # new
]


@pytest.fixture
def parts():
    database = SqliteDatabase(":memory:")
    use_case = ReuseSupplierPlan(
        FileSpreadsheetReader(),
        database.sessions,
        [ClassifierStage("heuristics", FakeClassifier(ROLES))],
        plans=database.plans,
        approvals=database,
    )
    reports = ReportPriceChanges(use_case.get, database.history, ReportCsvExporter())
    yield use_case, reports
    database.close()


@pytest.fixture
def client(parts):
    use_case, reports = parts
    app = create_app(ApiDependencies(use_case, reports=reports))
    return TestClient(app, raise_server_exceptions=False)


def approve(client, rows):
    state = upload(client, rows=rows).json()
    for question in state["questions"]:
        option = {"price_includes_vat": "yes", "currency": "ARS"}[question["id"]]
        answer(client, state["id"], question["id"], option)
    assert client.post(f"/imports/{state['id']}/approve").status_code == 200
    return state["id"]


def two_imports(client):
    approve(client, FIRST)
    return approve(client, SECOND)


def test_the_first_import_of_a_supplier_has_no_report(client):
    first = approve(client, FIRST)

    response = client.get(f"/imports/{first}/report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_previous_import"


def test_a_session_that_is_not_approved_has_no_report(client):
    approve(client, FIRST)
    pending = upload(client, rows=SECOND).json()["id"]

    response = client.get(f"/imports/{pending}/report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_operation"


def test_an_unknown_session_is_a_404(client):
    assert client.get("/imports/nope/report").status_code == 404
    assert client.get("/imports/nope/report/export").status_code == 404


def test_the_report_lists_every_section(client):
    second = two_imports(client)

    body = client.get(f"/imports/{second}/report").json()

    assert body["import_id"] == second
    assert body["supplier_name"] == "Ferreteria Ejemplo"
    assert body["threshold"] == "0.30"
    assert body["previous_import"]["record_count"] == 5
    assert body["current_import"]["import_id"] == second
    assert body["summary"] == {
        "unchanged": 1,
        "increases": 2,
        "decreases": 1,
        "from_zero": 0,
        "new_products": 1,
        "discontinued": 1,
        "currency_changed": 0,
        "ambiguous": 0,
        "anomalies": 2,
        "median_change_pct": "10.00",
    }
    assert body["increases"][0] == {
        "supplier_code": "A2",
        "description": "Tuerca",
        "currency": "ARS",
        "previous_cost": "800.00",
        "current_cost": "2400.00",
        "change": "1600.00",
        "change_pct": "200.00",
        "anomaly": True,
    }
    assert [item["supplier_code"] for item in body["increases"]] == ["A2", "A1"]
    assert [item["supplier_code"] for item in body["decreases"]] == ["A5"]
    assert [item["supplier_code"] for item in body["anomalies"]] == ["A2", "A5"]
    assert body["new_products"] == [
        {"supplier_code": "A7", "description": "Brida", "currency": "ARS", "unit_cost_net": "82.64"}
    ]
    assert [item["supplier_code"] for item in body["discontinued"]] == ["A3"]
    assert body["from_zero"] == body["currency_changed"] == body["ambiguous_codes"] == []


def test_the_threshold_is_adjustable(client):
    second = two_imports(client)

    loose = client.get(f"/imports/{second}/report", params={"threshold": "0.5"}).json()
    strict = client.get(f"/imports/{second}/report", params={"threshold": "0.05"}).json()

    assert loose["threshold"] == "0.5"
    assert [item["supplier_code"] for item in loose["anomalies"]] == ["A2"]
    assert [item["supplier_code"] for item in strict["anomalies"]] == ["A2", "A5", "A1"]


@pytest.mark.parametrize("threshold", ["abc", "-1", "nan", "30%"])
def test_an_unusable_threshold_is_a_422(client, threshold):
    second = two_imports(client)

    response = client.get(f"/imports/{second}/report", params={"threshold": threshold})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_input"


def test_the_report_downloads_as_csv(client):
    second = two_imports(client)

    response = client.get(f"/imports/{second}/report/export", params={"threshold": "0.30"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="pricor-ferreteria-ejemplo-{second[:8]}-price-changes.csv"'
    )
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"), newline="")))
    assert rows[0][:3] == ["section", "supplier_code", "description"]
    assert [(row[0], row[1], row[9]) for row in rows[1:]] == [
        ("increase", "A2", "yes"),
        ("increase", "A1", "no"),
        ("decrease", "A5", "yes"),
        ("new", "A7", ""),
        ("discontinued", "A3", ""),
    ]


def test_an_unknown_export_format_is_a_422(client):
    second = two_imports(client)

    response = client.get(f"/imports/{second}/report/export", params={"format": "pdf"})

    assert response.status_code == 422


def test_without_a_price_history_the_report_is_not_available(parts):
    use_case, _ = parts
    client = TestClient(create_app(ApiDependencies(use_case)), raise_server_exceptions=False)
    first = approve(client, FIRST)

    response = client.get(f"/imports/{first}/report")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_operation"


def test_the_wired_app_offers_price_reports(tmp_path):
    from pricor.entrypoints.wiring import dependencies_from_env

    dependencies = dependencies_from_env({"PRICOR_DB": str(tmp_path / "pricor.db")})

    assert isinstance(dependencies.reports, ReportPriceChanges)
