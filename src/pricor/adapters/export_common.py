"""Shared formatting rules of the file exporters."""

import csv
import io
from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pricor.domain.contract import ContractRecord
from pricor.ports.exporter import (
    CONTRACT_COLUMNS,
    CONVERTED_COLUMNS,
    REJECTED_COLUMNS,
    SUPPLIER_COLUMN,
    TRACEABILITY_COLUMNS,
    UNIT_PRICE_COLUMNS,
    ImportExport,
)

from pricor.ports.output_format import OUTPUT_FIELDS, OutputFormat, parse_decimal_text

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


def has_unit_price(data: ImportExport) -> bool:
    return any(item.record.unit_price is not None for item in data.accepted)


def has_conversion(data: ImportExport) -> bool:
    return any(item.record.unit_cost_net_converted is not None for item in data.accepted)


def product_columns(data: ImportExport) -> tuple[str, ...]:
    """The contract columns, optional unit price and converted columns when present, then traceability."""
    extra_unit = UNIT_PRICE_COLUMNS if has_unit_price(data) else ()
    extra_fx = CONVERTED_COLUMNS if has_conversion(data) else ()
    return (*CONTRACT_COLUMNS, *extra_unit, *extra_fx, *TRACEABILITY_COLUMNS)


def product_values(
    row_number: int, record: ContractRecord, converted: bool = False, unit_price: bool = False
) -> list[object]:
    """Typed values in `product_columns` order (Decimal/None for numbers, str for text)."""
    extra_unit = [record.unit_price] if unit_price else []
    extra = (
        [record.unit_cost_net_converted, record.fx_rate, record.fx_source, record.fx_date]
        if converted
        else []
    )
    return [
        record.supplier_code,
        record.description,
        record.unit_cost_net,
        record.currency,
        record.vat_rate,
        record.units_per_pack,
        record.barcode,
        record.suggested_retail_price,
        *extra_unit,
        *extra,
        row_number,
    ]



_CENTS = Decimal("0.01")


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return parse_decimal_text(value)
    return None


def apply_kind(value: object, kind: str | None) -> object:
    """Shape one value by its column type; `None` (legacy) and missing values stay as they are."""
    if kind is None or value is None:
        return value
    if kind in ("text", "description", "code"):
        return decimal_text(value) if isinstance(value, Decimal) else str(value)
    number = _as_decimal(value)
    if number is None:
        return value
    if kind != "price":
        return number
    try:
        return number.quantize(_CENTS, rounding=ROUND_HALF_UP)
    except InvalidOperation:  # too many digits for the context: keep the value as written
        return value


def formatted_product_values(
    row_number: int, record: ContractRecord, output_format: OutputFormat
) -> list[object]:
    """Project already-computed values, never interpret source text as code."""
    fields = dict(zip(OUTPUT_FIELDS, product_values(row_number, record, converted=True, unit_price=True), strict=True))
    values = []
    for column in output_format.columns:
        source = column.source
        if source is None:
            raise ValueError("output format has an unconfirmed source")
        if source == "empty":
            values.append(None)
        elif source.startswith("field:"):
            values.append(fields[source.removeprefix("field:")])
        elif source.startswith("constant:"):
            values.append(source.removeprefix("constant:"))
        else:
            raise ValueError("output format has an invalid source")
        values[-1] = apply_kind(values[-1], column.kind)
    return values


def combined_products(
    parts: Sequence[ImportExport], output_format: OutputFormat | None
) -> tuple[list[str], list[list[object]]]:
    """Header and rows of several imports in one table, the supplier name first on every row.

    Without a layout the converted columns appear when any import was converted.
    """
    if output_format is not None:
        header = [column.name for column in output_format.columns]
    else:
        unit_price = any(has_unit_price(part) for part in parts)
        converted = any(has_conversion(part) for part in parts)
        extra_unit = UNIT_PRICE_COLUMNS if unit_price else ()
        extra_fx = CONVERTED_COLUMNS if converted else ()
        header = [*CONTRACT_COLUMNS, *extra_unit, *extra_fx, *TRACEABILITY_COLUMNS]
    rows: list[list[object]] = []
    for part in parts:
        for item in part.accepted:
            values = (
                formatted_product_values(item.row_number, item.record, output_format)
                if output_format is not None
                else product_values(
                    item.row_number,
                    item.record,
                    "unit_cost_net_converted" in header,
                    "unit_price" in header,
                )
            )
            rows.append([part.supplier_name, *values])
    return [SUPPLIER_COLUMN, *header], rows


def combined_rejected(parts: Sequence[ImportExport]) -> tuple[list[str], list[list[object]]]:
    """The rejected report of several imports, padded with empty cells to the widest layout.

    Each supplier's file names its columns differently, so the original cells go under
    neutral `cell_1..cell_N` headings instead of one file's names.
    """
    cells_width = max((len(rejected_header(part)) - len(REJECTED_COLUMNS) for part in parts), default=0)
    widest = [*REJECTED_COLUMNS, *(f"cell_{n}" for n in range(1, cells_width + 1))]
    rows: list[list[object]] = [
        [
            part.supplier_name, entry.row_number, "; ".join(entry.reasons),
            *entry.cells, *[""] * (cells_width - len(entry.cells)),
        ]
        for part in parts
        for entry in part.rejected
    ]
    return [SUPPLIER_COLUMN, *widest], rows


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
