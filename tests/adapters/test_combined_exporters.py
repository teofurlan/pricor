"""Combined files of several imports: the supplier column, padding of rejected layouts."""

import csv
import io

import pytest
from openpyxl import load_workbook

from pricor.adapters.csv_exporter import CsvExporter
from pricor.adapters.xlsx_exporter import XlsxExporter
from pricor.ports.exporter import ImportExport, RejectedEntry


def part(supplier, headers, entries):
    return ImportExport(supplier, (), tuple(RejectedEntry(*e) for e in entries), tuple(headers))


NARROW = part("Alfa", ["a", "b"], [(2, ("1", "2"), ("bad",))])
WIDE = part("Beta", ["a", "b", "c", "d"], [(5, ("x", "y", "z", "w"), ("worse", "much"))])


def test_csv_rejected_layouts_are_padded_to_the_widest():
    out = list(csv.reader(io.StringIO(CsvExporter().export_rejected_combined([NARROW, WIDE]).decode("utf-8-sig"))))
    assert out == [
        ["supplier", "source_row", "reasons", "a", "b", "c", "d"],
        ["Alfa", "2", "bad", "1", "2", "", ""],
        ["Beta", "5", "worse; much", "x", "y", "z", "w"],
    ]


def test_csv_rejected_order_does_not_change_the_widest_header():
    out = list(csv.reader(io.StringIO(CsvExporter().export_rejected_combined([WIDE, NARROW]).decode("utf-8-sig"))))
    assert out[0] == ["supplier", "source_row", "reasons", "a", "b", "c", "d"]
    assert out[2] == ["Alfa", "2", "bad", "1", "2", "", ""]


def test_xlsx_rejected_pads_and_keeps_text_text():
    evil = part("=Sum", ["a"], [(3, ("=1+1",), ("r",))])
    sheet = load_workbook(io.BytesIO(XlsxExporter().export_rejected_combined([evil, WIDE])))["Rejected rows"]
    assert [c.value for c in sheet[1]] == ["supplier", "source_row", "reasons", "a", "b", "c", "d"]
    assert sheet["A2"].value == "=Sum" and sheet["A2"].data_type == "s"
    assert sheet["D2"].value == "=1+1" and sheet["D2"].data_type == "s"
    assert sheet["B2"].value == 3 and sheet["E2"].value is None
    assert sheet.freeze_panes == "A2"


@pytest.mark.parametrize("exporter", [CsvExporter(), XlsxExporter()])
def test_combined_with_no_rejected_rows_is_a_header_only_file(exporter):
    clean = ImportExport("Alfa", (), (), ("a",))
    content = exporter.export_rejected_combined([clean])
    assert content
