import pytest

from pricor.adapters.pdf_table_reader import PdfTableReader
from pricor.ports.spreadsheet import SpreadsheetError

from .pdf_fixtures import pdf_bytes


def write(tmp_path, pages, name="template.pdf"):
    path = tmp_path / name
    path.write_bytes(pdf_bytes(pages))
    return path


def test_reads_the_rows_of_a_ruled_table(tmp_path):
    path = write(tmp_path, [[["Codigo", "Detalle", "Costo"], ["001", "Tornillo", "10,50"]]])
    assert PdfTableReader().read_sheet(path).rows == (
        ("Codigo", "Detalle", "Costo"), ("001", "Tornillo", "10,50"),
    )


def test_first_table_across_pages_skips_text_only_pages(tmp_path):
    path = write(tmp_path, [["just a paragraph"], [["SKU", "Nota"], ["1", "x"]], [["Other", "Table"]]])
    assert PdfTableReader().read_sheet(path).rows[0] == ("SKU", "Nota")


def test_pdf_without_a_table_is_a_spreadsheet_error(tmp_path):
    path = write(tmp_path, [["only text, no ruled table"]])
    with pytest.raises(SpreadsheetError, match="no table"):
        PdfTableReader().read_sheet(path)


def test_single_column_table_does_not_count(tmp_path):
    path = write(tmp_path, [[["Only"], ["one"]]])
    with pytest.raises(SpreadsheetError, match="no table"):
        PdfTableReader().read_sheet(path)


def test_corrupt_pdf_is_a_spreadsheet_error(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.4 not really")
    with pytest.raises(SpreadsheetError):
        PdfTableReader().read_sheet(path)
