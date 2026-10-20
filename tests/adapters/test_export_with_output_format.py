import csv
import io
import datetime as dt
import zipfile
from decimal import Decimal
from types import SimpleNamespace

import openpyxl.packaging.core as core_properties
import openpyxl.writer.excel as excel_writer

import pytest
from openpyxl import load_workbook

from pricor.adapters.csv_exporter import CsvExporter
from pricor.adapters.xlsx_exporter import XlsxExporter
from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.application.export_import import ExportImport
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.domain.contract import ContractRecord
from pricor.ports.output_format import OUTPUT_FIELDS
from pricor.ports.price_history import ImportedRecord

from .exports import sample
from ..persistence.sessions import Flow


def csv_rows(content):
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def cells(content, name="Products"):
    return [[(c.value, c.data_type, c.number_format) for c in row] for row in load_workbook(io.BytesIO(content))[name]]


@pytest.fixture(autouse=True)
def fixed_xlsx_clock(monkeypatch):
    """Freeze only container/document timestamps so byte comparisons are meaningful."""
    class FixedDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 19, 12, 0, 0, tzinfo=tz)

    clock = SimpleNamespace(datetime=FixedDateTime, timezone=dt.timezone)
    monkeypatch.setattr(core_properties, "datetime", clock)
    monkeypatch.setattr(excel_writer, "datetime", clock)
    monkeypatch.setattr(zipfile, "time", SimpleNamespace(
        time=lambda: 1792411200,
        localtime=lambda *args: (2026, 10, 19, 12, 0, 0, 0, 292, -1),
    ))


@pytest.fixture
def setup_format(tmp_path):
    db = SqliteDatabase(":memory:")
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    path = tmp_path / "format.csv"
    path.write_text("Code,Net,Blank,Fixed,Again,Missing,Converted,Row\n", encoding="utf-8")
    manager.upload(path)
    yield manager, db.output_format
    db.close()


def confirm(manager):
    return manager.confirm(["field:supplier_code", "field:unit_cost_net", "empty", "constant:=1+1", "field:supplier_code", "field:barcode", "field:unit_cost_net_converted", "field:source_row"])


@pytest.mark.parametrize("exporter", [CsvExporter(), XlsxExporter()], ids=["csv", "xlsx"])
def test_confirmed_format_exact_names_order_values_and_unchanged_rejected(setup_format, exporter):
    manager, store = setup_format
    fmt = confirm(manager)
    record = ContractRecord("00123", "Product", Decimal("855.00"), "ARS", unit_cost_net_converted=Decimal("12345678901234567.89"))
    data = sample(accepted=[ImportedRecord(3, record)])
    before_rejected = exporter.export_rejected(data)
    before_embedded = cells(exporter.export(data), "Rejected rows") if exporter.format == "xlsx" else None
    content = exporter.export_formatted(data, fmt)
    if exporter.format == "csv":
        assert csv_rows(content) == [[c.name for c in fmt.columns], ["00123", "855.00", "", "'=1+1", "00123", "", "12345678901234567.89", "3"]]
        assert exporter.export_rejected(data) == before_rejected
    else:
        sheet = cells(content)
        assert [c[0] for c in sheet[0]] == [c.name for c in fmt.columns]
        assert [c[0] for c in sheet[1]] == ["00123", 855, None, "=1+1", "00123", None, "12345678901234567.89", 3]
        assert [sheet[1][i][1] for i in (0, 3, 4, 6)] == ["s"] * 4
        assert sheet[1][1][1:] == ("n", "0.00")
        assert sheet[1][7][1] == "n"
        assert cells(content, "Rejected rows") == before_embedded
        assert exporter.export_rejected(data) == before_rejected


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_use_case_applies_only_confirmed_format_and_never_changes_rejected(setup_format, format):
    manager, store = setup_format
    flow = Flow()
    session = flow.approved()
    baseline = ExportImport(flow.use_case.get, [CsvExporter(), XlsxExporter()])
    exports = ExportImport(flow.use_case.get, [CsvExporter(), XlsxExporter()], output_format=store)
    original = baseline.products(session.id, format).content
    proposed = exports.products(session.id, format).content
    assert proposed == original
    before_rejected = exports.rejected(session.id, format).content
    confirm(manager)
    mapped = exports.products(session.id, format).content
    expected = ["Code", "Net", "Blank", "Fixed", "Again", "Missing", "Converted", "Row"]
    if format == "csv":
        assert csv_rows(mapped)[0] == expected
        assert exports.rejected(session.id, format).content == before_rejected
    else:
        assert [c[0] for c in cells(mapped)[0]] == expected
        assert cells(mapped, "Rejected rows") == cells(before_rejected, "Rejected rows")
    assert exports.rejected(session.id, format).content == before_rejected
    manager.delete()
    restored = exports.products(session.id, format).content
    assert restored == original


@pytest.mark.parametrize("exporter", [CsvExporter(), XlsxExporter()], ids=["csv", "xlsx"])
def test_all_closed_fields_use_existing_text_and_number_rules(tmp_path, exporter):
    db = SqliteDatabase(":memory:")
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    path = tmp_path / "all.csv"
    path.write_text(",".join(OUTPUT_FIELDS) + "\n", encoding="utf-8")
    manager.upload(path)
    fmt = manager.confirm([f"field:{name}" for name in OUTPUT_FIELDS])
    record = ContractRecord("001", "=formula", Decimal("1.20"), "USD", Decimal("21"), Decimal("12"), "0007", Decimal("2.30"), Decimal("1200.00"), Decimal("1000.00"), "manual", "2026-10-19")
    data = sample(accepted=[ImportedRecord(7, record)])
    content = exporter.export_formatted(data, fmt)
    if exporter.format == "csv":
        assert csv_rows(content) == [list(OUTPUT_FIELDS), ["001", "'=formula", "1.20", "USD", "21", "12", "0007", "2.30", "1200.00", "1000.00", "manual", "2026-10-19", "7"]]
    else:
        mapped = cells(content)
        standard = cells(exporter.export(data))
        assert mapped == standard
    db.close()


def test_no_format_csv_stays_byte_identical():
    assert CsvExporter().export(sample(accepted=[], rejected=[])) == b"\xef\xbb\xbfsupplier_code,description,unit_cost_net,currency,vat_rate,units_per_pack,barcode,suggested_retail_price,source_row\r\n"
