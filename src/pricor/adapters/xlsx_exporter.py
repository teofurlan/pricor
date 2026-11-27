"""XLSX exporter (openpyxl).

The workbook has a `Products` sheet (contract columns + traceability) and a
`Rejected rows` sheet. Text is always stored as a text cell, never as a
formula, so a supplier's `=...` cannot run; codes, barcodes and original cells
keep leading zeros. Money and rates are numeric cells whose number format shows
their own decimals. A spreadsheet number is an IEEE double, exact up to 15
significant digits: a decimal with more digits is written as text instead of
being rounded silently.
"""

import io
from collections.abc import Sequence
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from pricor.adapters.export_common import (
    combined_products,
    combined_rejected,
    formatted_product_values,
    has_conversion,
    has_unit_price,
    product_columns,
    product_values,
    rejected_header,
    rejected_width,
)
from pricor.ports.exporter import ImportExport
from pricor.ports.output_format import OutputFormat

PRODUCTS_SHEET = "Products"
REJECTED_SHEET = "Rejected rows"
MAX_EXACT_DIGITS = 15
_TEXT_COLUMNS = frozenset(
    {"supplier_code", "description", "currency", "barcode", "fx_source", "fx_date"}
)


def _set_text(sheet: Worksheet, row: int, column: int, text: str) -> None:
    cell = sheet.cell(row=row, column=column, value=text)
    cell.data_type = "s"  # assigning "=..." would otherwise make it a formula
    cell.number_format = "@"


def _set_number(sheet: Worksheet, row: int, column: int, value: Decimal | int) -> None:
    if isinstance(value, Decimal) and len(value.normalize().as_tuple().digits) > MAX_EXACT_DIGITS:
        _set_text(sheet, row, column, format(value, "f"))
        return
    cell = sheet.cell(row=row, column=column, value=value)
    decimals = -value.as_tuple().exponent if isinstance(value, Decimal) else 0
    cell.number_format = "0." + "0" * decimals if decimals > 0 else "0"


def _header(sheet: Worksheet, names: list[str]) -> None:
    for column, name in enumerate(names, start=1):
        _set_text(sheet, 1, column, name)
        sheet.cell(row=1, column=column).font = Font(bold=True)
    sheet.freeze_panes = "A2"


def _products(sheet: Worksheet, data: ImportExport, output_format: OutputFormat | None = None) -> None:
    names = tuple(c.name for c in output_format.columns) if output_format else product_columns(data)
    converted = has_conversion(data)
    unit_price = has_unit_price(data)
    _header(sheet, list(names))
    for row, item in enumerate(data.accepted, start=2):
        values = (
            formatted_product_values(item.row_number, item.record, output_format)
            if output_format else product_values(item.row_number, item.record, converted, unit_price)
        )
        for column, (name, value) in enumerate(zip(names, values, strict=True), start=1):
            if value is None:
                continue
            if (isinstance(value, str) if output_format else name in _TEXT_COLUMNS):
                _set_text(sheet, row, column, value)
            else:
                _set_number(sheet, row, column, value)


def _rejected(sheet: Worksheet, data: ImportExport) -> None:
    _header(sheet, rejected_header(data))
    width = rejected_width(data)
    for row, entry in enumerate(data.rejected, start=2):
        sheet.cell(row=row, column=1, value=entry.row_number)
        _set_text(sheet, row, 2, "; ".join(entry.reasons))
        for offset in range(width):
            if offset < len(entry.cells) and entry.cells[offset] != "":
                _set_text(sheet, row, 3 + offset, entry.cells[offset])


def _table(sheet: Worksheet, header: list[str], rows: list[list[object]]) -> None:
    """Header and rows: strings as text cells, numbers as numeric cells."""
    _header(sheet, header)
    for row, values in enumerate(rows, start=2):
        for column, value in enumerate(values, start=1):
            if value is None or value == "":
                continue
            if isinstance(value, str):
                _set_text(sheet, row, column, value)
            else:
                _set_number(sheet, row, column, value)


def _save(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class XlsxExporter:
    format = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    extension = ".xlsx"

    def export(self, data: ImportExport) -> bytes:
        book = Workbook()
        products = book.active
        products.title = PRODUCTS_SHEET
        _products(products, data)
        _rejected(book.create_sheet(REJECTED_SHEET), data)
        return _save(book)

    def export_formatted(self, data: ImportExport, output_format: OutputFormat) -> bytes:
        if output_format.state != "confirmed":
            return self.export(data)
        book = Workbook()
        products = book.active
        products.title = PRODUCTS_SHEET
        _products(products, data, output_format)
        _rejected(book.create_sheet(REJECTED_SHEET), data)
        return _save(book)

    def export_rejected(self, data: ImportExport) -> bytes:
        book = Workbook()
        report = book.active
        report.title = REJECTED_SHEET
        _rejected(report, data)
        return _save(book)

    def export_combined(self, parts: Sequence[ImportExport], output_format: OutputFormat | None) -> bytes:
        header, rows = combined_products(parts, output_format)
        book = Workbook()
        products = book.active
        products.title = PRODUCTS_SHEET
        _table(products, header, rows)
        return _save(book)

    def export_rejected_combined(self, parts: Sequence[ImportExport]) -> bytes:
        header, rows = combined_rejected(parts)
        book = Workbook()
        report = book.active
        report.title = REJECTED_SHEET
        _table(report, header, rows)
        return _save(book)
