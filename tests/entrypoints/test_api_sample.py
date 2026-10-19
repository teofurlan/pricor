import csv
import io
import pytest
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.import_first_time import ImportFirstTime
from pricor.domain.roles import ColumnRole as R
from pricor.entrypoints.api import ApiDependencies, create_app
from tests.application.fakes import FakeClassifier
from pricor.application.cascade import ClassifierStage

ROLES = {
    "Codigo": (R.CODE, 0.95),
    "Descripcion": (R.DESCRIPTION, 0.95),
    "Precio lista": (R.COST_PRICE, 0.9),
    "IVA": (R.VAT_RATE, 0.9),
}

ROWS = [
    ["LISTA OCTUBRE", "", "", ""],  # Preamble (row 0)
    ["Codigo", "Descripcion", "Precio lista", "IVA"],  # Header (row 1)
    ["A1", "Tornillo", "1.210,00", "21%"],  # Data 1
    ["A2", "Tuerca", "968,00", "21%"],  # Data 2
    ["SECCION HERRAMIENTAS", "", "", ""],  # Section row
    ["A3", "Arandela", "121,00", "21%"],  # Data 3
    ["A4", "Clavo", "60,50", "21%"],  # Data 4
    ["A5", "Taco", "1.815,00", "21%"],  # Data 5
    ["A6", "Brida", "500,00", "21%"],  # Data 6
    ["", "", "", ""],  # Empty row
    ["TOTAL", "", "4.174,50", ""],  # Total row
]


def csv_bytes(rows):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode("utf-8")


def make_client():
    stages = [ClassifierStage("heuristics", FakeClassifier(ROLES))]
    reader = FileSpreadsheetReader()
    use_case = ImportFirstTime(
        reader, InMemoryImportSessionRepository(), stages, None
    )
    app = create_app(ApiDependencies(use_case, reader=reader))
    return TestClient(app, raise_server_exceptions=False)


def test_sample_happy_path():
    client = make_client()
    upload_res = client.post(
        "/imports",
        files={"file": ("lista.csv", csv_bytes(ROWS), "text/csv")},
        data={"supplier_name": "Proveedor"},
    )
    assert upload_res.status_code == 201
    session_id = upload_res.json()["id"]

    sample_res = client.get(f"/imports/{session_id}/sample")
    assert sample_res.status_code == 200
    data = sample_res.json()
    assert data["header"] == ["Codigo", "Descripcion", "Precio lista", "IVA"]
    # Default limit=5 data rows, skipping preamble, header, section, empty, total
    assert len(data["rows"]) == 5
    assert data["rows"][0] == ["A1", "Tornillo", "1.210,00", "21%"]
    assert data["rows"][1] == ["A2", "Tuerca", "968,00", "21%"]
    assert data["rows"][2] == ["A3", "Arandela", "121,00", "21%"]
    assert data["rows"][3] == ["A4", "Clavo", "60,50", "21%"]
    assert data["rows"][4] == ["A5", "Taco", "1.815,00", "21%"]


def test_sample_custom_limit():
    client = make_client()
    upload_res = client.post(
        "/imports",
        files={"file": ("lista.csv", csv_bytes(ROWS), "text/csv")},
        data={"supplier_name": "Proveedor"},
    )
    session_id = upload_res.json()["id"]

    sample_res = client.get(f"/imports/{session_id}/sample?limit=2")
    assert sample_res.status_code == 200
    data = sample_res.json()
    assert len(data["rows"]) == 2
    assert data["rows"][0] == ["A1", "Tornillo", "1.210,00", "21%"]
    assert data["rows"][1] == ["A2", "Tuerca", "968,00", "21%"]


@pytest.mark.parametrize("bad_limit", [0, -1, 21, 100])
def test_sample_limit_bounds(bad_limit):
    client = make_client()
    upload_res = client.post(
        "/imports",
        files={"file": ("lista.csv", csv_bytes(ROWS), "text/csv")},
        data={"supplier_name": "Proveedor"},
    )
    session_id = upload_res.json()["id"]

    sample_res = client.get(f"/imports/{session_id}/sample?limit={bad_limit}")
    assert sample_res.status_code == 422
    assert sample_res.json()["error"]["code"] in ("invalid_input", "invalid_request")


def test_sample_unknown_session():
    client = make_client()
    sample_res = client.get("/imports/nonexistent-session/sample")
    assert sample_res.status_code == 404
    assert sample_res.json()["error"]["code"] == "session_not_found"
