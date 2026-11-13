"""CSV exporter.

Format: UTF-8 with a byte-order mark (so Excel detects the encoding), `,` as
delimiter, CRLF line ends and RFC 4180 quoting. Every value is written as
text; decimals keep their own digits (`855.00`) and use `.` as the decimal
separator. A spreadsheet program that turns text into numbers on open will drop
leading zeros of codes: use the XLSX export for that, or import the CSV with the
code columns declared as text. Excel installed with a `;` list separator (es-AR)
needs `CsvExporter(delimiter=";")`.

Text that a spreadsheet would run as a formula is neutralized (see `neutralize`).
"""

from collections.abc import Sequence

from pricor.adapters.export_common import (
    combined_products,
    combined_rejected,
    csv_bytes,
    formatted_product_values,
    has_conversion,
    product_columns,
    product_values,
    rejected_header,
    rejected_width,
)
from pricor.ports.exporter import ImportExport
from pricor.ports.output_format import OutputFormat


class CsvExporter:
    format = "csv"
    media_type = "text/csv; charset=utf-8"
    extension = ".csv"

    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter

    def export(self, data: ImportExport) -> bytes:
        converted = has_conversion(data)
        rows = (product_values(item.row_number, item.record, converted) for item in data.accepted)
        return csv_bytes(product_columns(data), rows, self.delimiter)

    def export_formatted(self, data: ImportExport, output_format: OutputFormat) -> bytes:
        if output_format.state != "confirmed":
            return self.export(data)
        rows = (formatted_product_values(item.row_number, item.record, output_format) for item in data.accepted)
        return csv_bytes((column.name for column in output_format.columns), rows, self.delimiter)

    def export_rejected(self, data: ImportExport) -> bytes:
        width = rejected_width(data)
        rows = (
            [entry.row_number, "; ".join(entry.reasons), *entry.cells, *[""] * (width - len(entry.cells))]
            for entry in data.rejected
        )
        return csv_bytes(rejected_header(data), rows, self.delimiter)

    def export_combined(self, parts: Sequence[ImportExport], output_format: OutputFormat | None) -> bytes:
        header, rows = combined_products(parts, output_format)
        return csv_bytes(header, rows, self.delimiter)

    def export_rejected_combined(self, parts: Sequence[ImportExport]) -> bytes:
        header, rows = combined_rejected(parts)
        return csv_bytes(header, rows, self.delimiter)
