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

import csv
import io
from collections.abc import Iterable

from pricor.adapters.export_common import (
    decimal_text,
    neutralize,
    product_values,
    rejected_header,
    rejected_width,
)
from pricor.ports.exporter import PRODUCT_COLUMNS, ImportExport

_BOM = b"\xef\xbb\xbf"


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return neutralize(value)
    return decimal_text(value) if not isinstance(value, int) else str(value)


class CsvExporter:
    format = "csv"
    media_type = "text/csv; charset=utf-8"
    extension = ".csv"

    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter

    def export(self, data: ImportExport) -> bytes:
        rows = (product_values(item.row_number, item.record) for item in data.accepted)
        return self._write(PRODUCT_COLUMNS, rows)

    def export_rejected(self, data: ImportExport) -> bytes:
        width = rejected_width(data)
        rows = (
            [entry.row_number, "; ".join(entry.reasons), *entry.cells, *[""] * (width - len(entry.cells))]
            for entry in data.rejected
        )
        return self._write(rejected_header(data), rows)

    def _write(self, header: Iterable[str], rows: Iterable[list[object]]) -> bytes:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=self.delimiter, lineterminator="\r\n")
        writer.writerow(_cell(name) for name in header)
        for row in rows:
            writer.writerow(_cell(value) for value in row)
        return _BOM + buffer.getvalue().encode("utf-8")
