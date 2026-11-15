"""One file with the accepted (or rejected) rows of several approved imports, one `supplier` column first."""

import csv
import io

import pytest
from openpyxl import load_workbook

from pricor.adapters.csv_exporter import CsvExporter
from pricor.adapters.heuristic_output_format import HeuristicOutputFormat
from pricor.adapters.memory_session_repository import InMemoryImportSessionRepository
from pricor.adapters.spreadsheet_reader import FileSpreadsheetReader
from pricor.adapters.sqlite_store import SqliteDatabase
from pricor.adapters.xlsx_exporter import XlsxExporter
from pricor.application.errors import InvalidInputError, InvalidOperationError
from pricor.application.export_import import ExportImport
from pricor.application.manage_output_format import ManageOutputFormat
from pricor.ports.import_session_repository import SessionNotFoundError

from ..persistence.sessions import ROWS, Flow


@pytest.fixture
def world():
    db = SqliteDatabase(":memory:")
    manager = ManageOutputFormat(FileSpreadsheetReader(), db.output_format, HeuristicOutputFormat())
    repo = InMemoryImportSessionRepository()

    def approved(supplier, rows=ROWS):
        flow = Flow(repository=repo, rows=rows, supplier=supplier, output_formats=db.output_format)
        return flow.approved()

    flow = Flow(repository=repo, output_formats=db.output_format)
    exports = ExportImport(flow.use_case.get, [CsvExporter(), XlsxExporter()], output_format=db.output_format)
    yield approved, manager, exports, flow
    db.close()


def rows_of(file):
    return list(csv.reader(io.StringIO(file.content.decode("utf-8-sig"), newline="")))


def test_standard_products_have_one_header_supplier_first_and_sessions_in_given_order(world):
    approved, _, exports, _ = world
    a, b = approved("Alfa"), approved("Beta")
    single = rows_of(exports.products(a.id, "csv"))
    combined = rows_of(exports.combined([b.id, a.id], "csv", "products"))
    assert combined[0] == ["supplier", *single[0]]
    body = combined[1:]
    assert len(body) == 2 * (len(single) - 1)
    half = len(body) // 2
    assert {row[0] for row in body[:half]} == {"Beta"} and {row[0] for row in body[half:]} == {"Alfa"}
    assert [row[1:] for row in body[half:]] == single[1:]


def test_filename_and_media_type(world):
    approved, _, exports, _ = world
    a, b = approved("Alfa"), approved("Beta")
    csv_file = exports.combined([a.id, b.id], "csv", "products")
    assert (csv_file.filename, csv_file.media_type) == ("pricor-combined-2-files-products.csv", "text/csv; charset=utf-8")
    xlsx = exports.combined([a.id, b.id], "xlsx", "rejected")
    assert xlsx.filename == "pricor-combined-2-files-rejected.xlsx"
    assert xlsx.media_type == XlsxExporter.media_type


def test_custom_frozen_format_is_used_with_supplier_column_and_kinds(world):
    approved, manager, exports, _ = world
    manager.define([("SKU", "field:supplier_code", None, "code"), ("Costo", "field:unit_cost_net", None, "price")])
    a, b = approved("Alfa"), approved("Beta")
    single = rows_of(exports.products(a.id, "csv"))
    combined = rows_of(exports.combined([a.id, b.id], "csv", "products"))
    assert combined[0] == ["supplier", "SKU", "Costo"]
    assert combined[1][1:] == single[1]
    book = load_workbook(io.BytesIO(exports.combined([a.id, b.id], "xlsx", "products").content))
    sheet = book["Products"]
    assert [c.value for c in sheet[1]] == ["supplier", "SKU", "Costo"]
    assert sheet["A2"].value == "Alfa" and sheet["B2"].number_format == "@" and sheet["C2"].number_format == "0.00"


def test_formula_text_stays_neutralized(world):
    approved, _, exports, _ = world
    rows = [r for r in ROWS]
    rows[2] = ("=CMD()", "Tornillo", "1.210,00", "21%")
    a = approved("=EVIL", rows)
    combined = rows_of(exports.combined([a.id], "csv", "products"))
    assert combined[1][0] == "'=EVIL" and combined[1][1] == "'=CMD()"
    sheet = load_workbook(io.BytesIO(exports.combined([a.id], "xlsx", "products").content))["Products"]
    assert sheet["A2"].data_type == "s" and sheet["A2"].value == "=EVIL"


def test_different_frozen_formats_conflict(world):
    approved, manager, exports, _ = world
    manager.define([("SKU", "field:supplier_code", None)])
    a = approved("Alfa")
    manager.define([("Codigo", "field:supplier_code", None)])
    b = approved("Beta")
    with pytest.raises(InvalidOperationError, match="different output formats"):
        exports.combined([a.id, b.id], "csv", "products")


def test_standard_and_custom_conflict_but_equal_formats_do_not(world):
    approved, manager, exports, _ = world
    standard = approved("Std")
    manager.define([("SKU", "field:supplier_code", None)])
    c1, c2 = approved("C1"), approved("C2")
    with pytest.raises(InvalidOperationError):
        exports.combined([standard.id, c1.id], "csv", "products")
    assert rows_of(exports.combined([c1.id, c2.id], "csv", "products"))[0] == ["supplier", "SKU"]


def test_rejected_report_is_not_blocked_by_differing_formats(world):
    approved, manager, exports, _ = world
    a = approved("Alfa")
    manager.define([("SKU", "field:supplier_code", None)])
    b = approved("Beta")
    out = rows_of(exports.combined([a.id, b.id], "csv", "rejected"))
    single = rows_of(exports.rejected(a.id, "csv"))
    # Original cells go under neutral headings: each supplier's file names its columns differently.
    cells = len(single[0]) - 2
    assert out[0] == ["supplier", "source_row", "reasons", *(f"cell_{n}" for n in range(1, cells + 1))]
    assert single[0][:2] == ["source_row", "reasons"]
    assert {row[0] for row in out[1:]} == {"Alfa", "Beta"}


def test_unknown_session_is_not_found(world):
    approved, _, exports, _ = world
    a = approved("Alfa")
    with pytest.raises(SessionNotFoundError):
        exports.combined([a.id, "nope"], "csv", "products")


def test_session_not_approved_conflicts(world):
    approved, _, exports, flow = world
    a = approved("Alfa")
    ready = flow.ready()
    with pytest.raises(InvalidOperationError):
        exports.combined([a.id, ready.id], "csv", "products")


@pytest.mark.parametrize("count", [0, 51])
def test_empty_or_over_fifty_is_invalid(world, count):
    _, _, exports, _ = world
    with pytest.raises(InvalidInputError):
        exports.combined([f"id{i}" for i in range(count)], "csv", "products")


def test_duplicate_ids_are_invalid(world):
    approved, _, exports, _ = world
    a = approved("Alfa")
    with pytest.raises(InvalidInputError):
        exports.combined([a.id, a.id], "csv", "products")


def test_unknown_format_or_kind_is_invalid(world):
    approved, _, exports, _ = world
    a = approved("Alfa")
    with pytest.raises(InvalidInputError):
        exports.combined([a.id], "pdf", "products")
    with pytest.raises(InvalidInputError):
        exports.combined([a.id], "csv", "other")
