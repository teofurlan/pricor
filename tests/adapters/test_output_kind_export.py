"""Each column kind's effect on the CSV and XLSX products file."""

import csv
import io
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from pricor.adapters.csv_exporter import CsvExporter
from pricor.adapters.xlsx_exporter import XlsxExporter
from pricor.domain.contract import ContractRecord
from pricor.ports.output_format import OutputColumn, OutputFormat, OutputProposal
from pricor.ports.price_history import ImportedRecord

from .exports import sample


def fmt(*specs):
    """specs: (source, kind)"""
    columns = tuple(
        OutputColumn(i, f"C{i}", (), OutputProposal(source, "user", 1.0), source, kind)
        for i, (source, kind) in enumerate(specs)
    )
    return OutputFormat("t", "confirmed", columns)


def data(**overrides):
    record = ContractRecord(
        "0012", "Tornillo", Decimal("10.005"), "ARS", Decimal("21"), Decimal("12"), "0779",
        Decimal("1.234"),
    )
    return sample(accepted=[ImportedRecord(4, record)], rejected=[])


def csv_row(content):
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))[1]


def xlsx_row(content):
    return [(c.value, c.number_format, c.data_type) for c in list(load_workbook(io.BytesIO(content))["Products"])[1]]


def test_price_rounds_half_up_to_cents_in_csv_and_xlsx():
    fmt_ = fmt(("field:unit_cost_net", "price"), ("field:suggested_retail_price", "price"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["10.01", "1.23"]
    row = xlsx_row(XlsxExporter().export_formatted(data(), fmt_))
    assert [(v, f) for v, f, _ in row] == [(Decimal("10.01"), "0.00"), (Decimal("1.23"), "0.00")] or \
        [(float(v), f) for v, f, _ in row] == [(10.01, "0.00"), (1.23, "0.00")]


def test_price_pads_whole_numbers_to_two_decimals():
    record = ContractRecord("A", "B", Decimal("5"), "ARS")
    export = sample(accepted=[ImportedRecord(1, record)], rejected=[])
    fmt_ = fmt(("field:unit_cost_net", "price"))
    assert csv_row(CsvExporter().export_formatted(export, fmt_)) == ["5.00"]
    assert xlsx_row(XlsxExporter().export_formatted(export, fmt_))[0][1:] == ("0.00", "n")


def test_code_keeps_leading_zeros_with_text_format_in_xlsx():
    fmt_ = fmt(("field:supplier_code", "code"), ("field:barcode", "code"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["0012", "0779"]
    assert xlsx_row(XlsxExporter().export_formatted(data(), fmt_)) == [("0012", "@", "s"), ("0779", "@", "s")]


def test_text_and_description_write_the_value_as_text():
    fmt_ = fmt(("field:units_per_pack", "text"), ("field:description", "description"), ("field:source_row", "text"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["12", "Tornillo", "4"]
    assert [(v, d) for v, _, d in xlsx_row(XlsxExporter().export_formatted(data(), fmt_))] == [
        ("12", "s"), ("Tornillo", "s"), ("4", "s"),
    ]


def test_text_leaves_missing_values_empty():
    record = ContractRecord("A", "B", Decimal("5"), "ARS")
    export = sample(accepted=[ImportedRecord(1, record)], rejected=[])
    fmt_ = fmt(("field:barcode", "text"), ("empty", "text"), ("field:supplier_code", "text"))
    assert csv_row(CsvExporter().export_formatted(export, fmt_)) == ["", "", "A"]
    assert [v for v, _, _ in xlsx_row(XlsxExporter().export_formatted(export, fmt_))] == [None, None, "A"]


@pytest.mark.parametrize("constant,expected", [("constant:12,5", "12.5"), ("constant:7.25", "7.25"), ("constant:3", "3")])
def test_number_constant_becomes_a_number_cell(constant, expected):
    fmt_ = fmt((constant, "number"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == [expected]
    (value, _, kind), = xlsx_row(XlsxExporter().export_formatted(data(), fmt_))
    assert kind == "n" and Decimal(str(value)) == Decimal(expected)


def test_price_constant_is_rounded_and_formatted():
    fmt_ = fmt(("constant:9,995", "price"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["10.00"]
    (value, number_format, kind), = xlsx_row(XlsxExporter().export_formatted(data(), fmt_))
    assert (float(value), number_format, kind) == (10.0, "0.00", "n")


def test_number_keeps_the_field_decimals():
    fmt_ = fmt(("field:vat_rate", "number"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["21"]


def test_number_with_a_non_numeric_value_is_left_unchanged():
    fmt_ = fmt(("field:currency", "number"), ("field:currency", "price"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["ARS", "ARS"]


def test_legacy_kind_none_is_unchanged():
    fmt_ = fmt(("field:supplier_code", None), ("field:unit_cost_net", None), ("constant:12,5", None))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == ["0012", "10.005", "12,5"]
    row = xlsx_row(XlsxExporter().export_formatted(data(), fmt_))
    assert [(v if isinstance(v, str) else float(v), f, t) for v, f, t in row] == [
        ("0012", "@", "s"), (10.005, "0.000", "n"), ("12,5", "@", "s"),
    ]



def test_price_too_long_to_round_is_written_unchanged_instead_of_failing():
    huge = "9" * 30
    fmt_ = fmt((f"constant:{huge}", "price"))
    assert csv_row(CsvExporter().export_formatted(data(), fmt_)) == [huge]
