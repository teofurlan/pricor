"""How a profiled column becomes the text Laya classifies, and the question it answers.

Training (`tools/laya`) and inference must serialize columns identically, so both go through
this module. It never imports `laya` or `torch`: it only builds strings.

The state holds the header, the profiler's apparent type, a few sample values and simple
statistics of those samples. Cells and headers are untrusted: they are flattened to one line
and truncated, so a cell cannot add lines or fields to the state.
"""

import re
import statistics
from collections.abc import Sequence

from pricor.domain.profile import ColumnProfile
from pricor.domain.roles import ColumnRole

QUESTION_ID = "role"
MAX_SAMPLES = 5
MAX_HEADER_CHARS = 60
MAX_CELL_CHARS = 40
NO_HEADER = "(no header)"

# What each closed role means, in the words the model reads next to its options.
ROLE_CRITERIA: dict[str, str] = {
    ColumnRole.CODE.value: "product code, SKU, item or part number identifying the product (codigo, cod, ref, articulo)",
    ColumnRole.DESCRIPTION.value: "product name or free-text description of the item (descripcion, detalle, producto)",
    ColumnRole.COST_PRICE.value: "the supplier's list price that the buyer pays, wholesale cost (precio, precio lista, costo, P. Lista)",
    ColumnRole.RETAIL_PRICE.value: "suggested or final selling price to the public (precio venta, PVP, precio sugerido, publico)",
    ColumnRole.VAT_RATE.value: "VAT / IVA tax percentage such as 21 or 10.5 (alicuota IVA, IVA %)",
    ColumnRole.UNITS_PER_PACK.value: "number of units per box, pack or bundle (unidades por bulto, x caja, pack, UxB)",
    ColumnRole.BARCODE.value: "EAN / UPC barcode of 8-14 digits (codigo de barras, EAN)",
    ColumnRole.DISCOUNT.value: "discount or bonus percentage or quantity discount rule (bonificacion, descuento, dto)",
    ColumnRole.CURRENCY.value: "currency of the price: pesos, dollars, ARS, USD, u$s, moneda",
    ColumnRole.IGNORE.value: "any other column: brand, category, notes, flags, empty - not needed for pricing",
}
QUESTIONS: dict[str, dict] = {
    QUESTION_ID: {
        "type": "choice",
        "instructions": "What role does this spreadsheet column play in a supplier price list?",
        "criteria": ROLE_CRITERIA,
    }
}

_WHITESPACE = re.compile(r"\s+")
_MARKS = re.compile(r"[$%\s]")
_DOT_THOUSANDS = re.compile(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?")
_COMMA_THOUSANDS = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_PLAIN = re.compile(r"-?\d+(?:[.,]\d+)?")


def _flat(text: str, limit: int) -> str:
    return _WHITESPACE.sub(" ", text).strip()[:limit]


def _number(text: str) -> float | None:
    """The value of a plain number, a money or percent text, or grouped thousands; else None."""
    cleaned = _MARKS.sub("", text)
    if _DOT_THOUSANDS.fullmatch(cleaned):
        return float(cleaned.replace(".", "").replace(",", "."))
    if _COMMA_THOUSANDS.fullmatch(cleaned):
        return float(cleaned.replace(",", ""))
    if _PLAIN.fullmatch(cleaned):
        return float(cleaned.replace(",", "."))
    return None


def column_stats(values: Sequence[str]) -> str:
    """Simple statistics of the sample values: how many read as numbers, their range, lengths."""
    numbers = [number for value in values if (number := _number(value)) is not None]
    stats = f"numeric={len(numbers)}/{len(values)}"
    if numbers:
        stats += f" min={min(numbers):g} max={max(numbers):g}"
    if values:
        stats += f" avg_len={statistics.mean(len(value) for value in values):.1f}"
        stats += f" distinct={len(set(values))}"
    return stats


def serialize_column(header: str, column_type: str, samples: Sequence[str]) -> str:
    """The state text for one column: header, apparent type, sample values and their stats."""
    shown = [_flat(sample, MAX_CELL_CHARS) for sample in samples[:MAX_SAMPLES]]
    return "\n".join(
        (
            f"Column header: {_flat(header, MAX_HEADER_CHARS) or NO_HEADER}",
            f"Column type: {column_type}",
            f"Sample values: {' | '.join(shown)}",
            f"Stats: {column_stats(shown)}",
        )
    )


def state_for_column(column: ColumnProfile) -> str:
    """The state text for a profiled column (the same shape training examples have)."""
    return serialize_column(column.raw_header, column.apparent_type.value, column.samples)
