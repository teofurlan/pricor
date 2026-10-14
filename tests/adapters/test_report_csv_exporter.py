import csv
import io
from decimal import Decimal

from pricor.adapters.report_csv_exporter import REPORT_COLUMNS, ReportCsvExporter
from pricor.domain.contract import ContractRecord
from pricor.domain.price_report import compare_price_lists

D = Decimal


def record(code, cost, currency="ARS", description=None):
    return ContractRecord(code, description or f"Producto {code}", D(cost), currency)


def rows_of(data):
    assert data.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))


def export(previous, current, threshold=D("0.30")):
    return ReportCsvExporter().export(compare_price_lists(previous, current, threshold))


def test_it_is_a_csv_file_with_a_fixed_header():
    exporter = ReportCsvExporter()

    rows = rows_of(export([], []))

    assert (exporter.format, exporter.extension) == ("csv", ".csv")
    assert exporter.media_type == "text/csv; charset=utf-8"
    assert rows == [list(REPORT_COLUMNS)]
    assert REPORT_COLUMNS == (
        "section",
        "supplier_code",
        "description",
        "previous_currency",
        "current_currency",
        "previous_cost",
        "current_cost",
        "change",
        "change_percent",
        "anomaly",
        "note",
    )


def test_lines_end_with_crlf():
    assert b"\r\n" in export([record("A1", "1")], [record("A1", "2")])


def test_every_section_is_written_with_its_own_columns():
    previous = [
        record("UP", "100"),
        record("DOWN", "100"),
        record("BIG", "100"),
        record("ZERO", "0"),
        record("GONE", "7.5", "USD"),
        record("CUR", "10"),
        record("DUP", "1"),
        record("DUP", "2"),
        record("SAME", "5"),
    ]
    current = [
        record("UP", "104.25"),
        record("DOWN", "90"),
        record("BIG", "500"),
        record("ZERO", "3"),
        record("NEW", "12.00", "USD", description="Nuevo"),
        record("CUR", "0.01", "USD"),
        record("DUP", "1"),
        record("SAME", "5"),
    ]

    rows = rows_of(export(previous, current))

    by_section = {}
    for row in rows[1:]:
        by_section.setdefault(row[0], []).append(row)
    assert [row[1:] for row in by_section["increase"]] == [
        ["BIG", "Producto BIG", "ARS", "ARS", "100", "500", "400", "400.00", "yes", ""],
        ["UP", "Producto UP", "ARS", "ARS", "100", "104.25", "4.25", "4.25", "no", ""],
    ]
    assert [row[1:] for row in by_section["decrease"]] == [
        ["DOWN", "Producto DOWN", "ARS", "ARS", "100", "90", "-10", "-10.00", "no", ""]
    ]
    assert [row[1:] for row in by_section["from_zero"]] == [
        ["ZERO", "Producto ZERO", "ARS", "ARS", "0", "3", "3", "", "yes", ""]
    ]
    assert [row[1:] for row in by_section["new"]] == [
        ["NEW", "Nuevo", "", "USD", "", "12.00", "", "", "", ""]
    ]
    assert [row[1:] for row in by_section["discontinued"]] == [
        ["GONE", "Producto GONE", "USD", "", "7.5", "", "", "", "", ""]
    ]
    assert [row[1:] for row in by_section["currency_changed"]] == [
        ["CUR", "Producto CUR", "ARS", "USD", "10", "0.01", "", "", "", ""]
    ]
    assert [row[1:] for row in by_section["ambiguous"]] == [
        ["DUP", "", "", "", "", "", "", "", "", "appears 2 times in the previous list and 1 time in the current list"]
    ]
    assert "unchanged" not in by_section


def test_sections_follow_a_fixed_order():
    previous = [record("A", "1"), record("B", "10"), record("C", "1"), record("D", "1")]
    current = [record("A", "2"), record("B", "5"), record("N", "1")]

    sections = [row[0] for row in rows_of(export(previous, current))[1:]]

    assert sections == ["increase", "decrease", "new", "discontinued", "discontinued"]


def test_text_that_a_spreadsheet_would_run_is_neutralized():
    rows = rows_of(export([record("A1", "1", description="=1+1")], [record("A1", "2", description="=HYPERLINK()")]))

    assert rows[1][2] == "'=HYPERLINK()"
