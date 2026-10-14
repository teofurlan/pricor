"""Shared formatting rules of the file exporters."""

import csv
import io
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

from pricor.domain.contract import ContractRecord
from pricor.ports.exporter import REJECTED_COLUMNS, ImportExport

_BOM = b"\xef\xbb\xbf"
_CRLF = "\r\n"
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def decimal_text(value: Decimal | None) -> str:
    """Plain positional notation with the value's own digits (`855.00`, never `8.55E+2`)."""
    return "" if value is None else format(value, "f")


def is_plain_number(text: str) -> bool:
    try:
        return Decimal(text).is_finite()
    except InvalidOperation:
        return False


def neutralize(text: str) -> str:
    """Stop a spreadsheet program from running untrusted text as a formula (CSV injection).

    Text that begins with a formula character gets a leading apostrophe, except a
    plain number such as `-123`, which is not a formula and must stay intact.
    """
    if text.startswith(_FORMULA_STARTS) and not is_plain_number(text):
        return "'" + text
    return text


def rejected_header(data: ImportExport) -> list[str]:
    """Fixed columns, then one name per original cell (`column_N` where none is known)."""
    width = max((len(entry.cells) for entry in data.rejected), default=0)
    width = max(width, len(data.source_headers))
    names = [
        data.source_headers[i] if i < len(data.source_headers) else f"column_{i}"
        for i in range(width)
    ]
    return [*REJECTED_COLUMNS, *names]


def rejected_width(data: ImportExport) -> int:
    return len(rejected_header(data)) - len(REJECTED_COLUMNS)


def product_values(row_number: int, record: ContractRecord) -> list[object]:
    """Typed values in `PRODUCT_COLUMNS` order (Decimal/None for numbers, str for text)."""
    return [
        record.supplier_code,
        record.description,
        record.unit_cost_net,
        record.currency,
        record.vat_rate,
        record.units_per_pack,
        record.barcode,
        record.suggested_retail_price,
        row_number,
    ]



def csv_cell(value: object) -> str:
    """One CSV field: empty for `None`, formula-safe text, decimals in positional notation."""
    if value is None:
        return ""
    if isinstance(value, str):
        return neutralize(value)
    return decimal_text(value) if not isinstance(value, int) else str(value)


def csv_bytes(header: Iterable[str], rows: Iterable[list[object]], delimiter: str = ",") -> bytes:
    """UTF-8 with a byte-order mark (so Excel detects it), CRLF line ends, RFC 4180 quoting."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator=_CRLF)
    writer.writerow(csv_cell(name) for name in header)
    for row in rows:
        writer.writerow(csv_cell(value) for value in row)
    return _BOM + buffer.getvalue().encode("utf-8")
