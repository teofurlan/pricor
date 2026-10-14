import csv
import io
from decimal import Decimal

from pricor.adapters.csv_exporter import CsvExporter
from pricor.domain.contract import TargetField
from pricor.ports.exporter import CONTRACT_COLUMNS, PRODUCT_COLUMNS, RejectedEntry
from pricor.ports.price_history import ImportedRecord

from .exports import BARE, FULL, sample


def parse(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"), newline="")))


def test_contract_columns_follow_the_target_contract_order():
    assert CONTRACT_COLUMNS == tuple(field.value for field in TargetField)
    assert PRODUCT_COLUMNS == (*CONTRACT_COLUMNS, "source_row")


def test_products_file_has_a_bom_crlf_lines_and_the_fixed_header():
    content = CsvExporter().export(sample())
    assert content.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in content and b"\n\n" not in content
    assert parse(content)[0] == list(PRODUCT_COLUMNS)


def test_products_are_exact_text_with_traceability():
    rows = parse(CsvExporter().export(sample()))
    assert rows[1] == [
        "00123",  # leading zeros are kept
        'Tornillo 1/4", cabeza "plana"\nx100',  # RFC 4180 quoting round-trips
        "855.00",  # the exponent is not lost
        "ARS",
        "10.5",
        "12",
        "0779123456789",
        "1234.50",
        "3",
    ]
    assert rows[2] == ["A2", "Tuerca", "0.1", "USD", "", "", "", "", "8"]


def test_decimals_are_never_written_in_scientific_notation():
    from pricor.domain.contract import ContractRecord

    record = ContractRecord("A", "B", Decimal("1E+2"), "ARS", units_per_pack=Decimal("1E-7"))
    row = parse(CsvExporter().export(sample([ImportedRecord(1, record)])))[1]
    assert row[2] == "100"
    assert row[5] == "0.0000001"


def test_no_products_still_writes_the_header():
    assert parse(CsvExporter().export(sample(accepted=[]))) == [list(PRODUCT_COLUMNS)]


def test_formula_like_text_is_neutralized_but_plain_numbers_are_not():
    from pricor.domain.contract import ContractRecord

    record = ContractRecord(
        "-123", "=HYPERLINK(\"http://evil\")", Decimal("1"), "ARS", barcode="+54 11 4444"
    )
    row = parse(CsvExporter().export(sample([ImportedRecord(1, record)])))[1]
    assert row[0] == "-123"  # a plain number is not a formula
    assert row[1].startswith("'=HYPERLINK")
    assert row[6] == "'+54 11 4444"
    other = ContractRecord("@SUM(A1)", "\tcmd", Decimal("1"), "ARS")
    row = parse(CsvExporter().export(sample([ImportedRecord(1, other)])))[1]
    assert row[0] == "'@SUM(A1)" and row[1] == "'\tcmd"


def test_rejected_report_lists_every_row_with_original_cells_and_reasons():
    data = sample()
    rows = parse(CsvExporter().export_rejected(data))
    assert rows[0] == ["source_row", "reasons", "Codigo", "Descripcion", "Precio"]
    assert rows[1] == ["5", "Precio: not a number", "A9", "Brida", "abc"]
    assert rows[2] == ["6", "supplier_code is empty; x", "", "Sin codigo", "10,00"]
    assert len(rows) - 1 == len(data.rejected)


def test_rejected_report_names_cells_beyond_the_known_headers():
    wide = sample(rejected=[RejectedEntry(2, ("a", "b", "c", "d", "e"), ("bad",))])
    assert parse(CsvExporter().export_rejected(wide))[0] == [
        "source_row", "reasons", "Codigo", "Descripcion", "Precio", "column_3", "column_4",
    ]


def test_rejected_report_without_rejections_has_only_the_header():
    rows = parse(CsvExporter().export_rejected(sample(rejected=[])))
    assert rows == [["source_row", "reasons", "Codigo", "Descripcion", "Precio"]]


def test_rejected_cells_are_neutralized_too():
    data = sample(rejected=[RejectedEntry(2, ("=cmd|' /C calc'!A0",), ("=also",))])
    rows = parse(CsvExporter().export_rejected(data))
    assert rows[1][1] == "'=also" and rows[1][2].startswith("'=cmd")


def test_delimiter_is_configurable():
    content = CsvExporter(delimiter=";").export(sample([ImportedRecord(1, BARE)]))
    assert content.decode("utf-8-sig").splitlines()[0].startswith("supplier_code;description;")


def test_metadata():
    exporter = CsvExporter()
    assert (exporter.format, exporter.extension) == ("csv", ".csv")
    assert exporter.media_type.startswith("text/csv")
    assert FULL.supplier_code == "00123"
