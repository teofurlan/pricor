import io
import openpyxl
from fastapi.testclient import TestClient

from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.application.import_first_time import ImportFirstTime
from pricor.entrypoints.api import ApiDependencies, create_app


def make_client(max_upload_bytes=1024 * 1024):
    reader = FileSpreadsheetReader()
    use_case = ImportFirstTime(
        reader, InMemoryImportSessionRepository(), [], None
    )
    app = create_app(ApiDependencies(use_case, max_upload_bytes=max_upload_bytes, reader=reader))
    return TestClient(app, raise_server_exceptions=False)


def xlsx_bytes(sheets: dict[str, list[list]]):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_sheets_multisheet_xlsx():
    client = make_client()
    content = xlsx_bytes({
        "Precios": [["Codigo", "Precio"], ["A1", "100"]],
        "Descuentos": [["Codigo", "Desc"], ["A1", "10%"]],
    })
    response = client.post(
        "/sheets",
        files={"file": ("catalogo.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200
    assert response.json() == {"sheets": ["Precios", "Descuentos"]}


def test_sheets_csv():
    client = make_client()
    response = client.post(
        "/sheets",
        files={"file": ("lista_octubre.csv", b"Codigo,Precio\nA1,100\n", "text/csv")},
    )
    assert response.status_code == 200
    assert response.json() == {"sheets": ["lista_octubre"]}


def test_sheets_bad_extension():
    client = make_client()
    response = client.post(
        "/sheets",
        files={"file": ("catalogo.pdf", b"%PDF-1.4...", "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_format"


def test_sheets_file_too_large():
    client = make_client(max_upload_bytes=50)
    response = client.post(
        "/sheets",
        files={"file": ("lista.csv", b"a" * 100, "text/csv")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
