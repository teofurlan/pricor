"""Closed set of roles a source column can play in a supplier price list."""

import re
import unicodedata
from enum import StrEnum


class ColumnRole(StrEnum):
    CODE = "code"
    DESCRIPTION = "description"
    COST_PRICE = "cost_price"
    UNIT_PRICE = "unit_price"
    RETAIL_PRICE = "retail_price"
    VAT_RATE = "vat_rate"
    UNITS_PER_PACK = "units_per_pack"
    BARCODE = "barcode"
    DISCOUNT = "discount"
    CURRENCY = "currency"
    IGNORE = "ignore"


_PRICE_TOKENS = frozenset({"precio", "precios", "pcio", "prec", "pr", "p", "importe", "valor", "monto"})
_UNIT_MODIFIER_TOKENS = frozenset({"unitario", "unitaria", "unit", "unid", "unidad"})
_NON_UNIT_MODIFIERS = frozenset(
    {
        "lista", "costo", "neto", "mayorista", "mayor", "compra", "distribuidor", "dist",
        "venta", "sugerido", "sugerida", "publico", "pvp", "minorista", "pv", "recomendado", "final",
    }
)


def is_unit_price_header(raw_header: str) -> bool:
    """True when a header explicitly names a unit price (for example `PR. UNIT` or `Precio unitario`)."""
    decomposed = unicodedata.normalize("NFKD", raw_header)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    spaced = re.sub(r"(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", " ", stripped.casefold())
    tokens = set(re.sub(r"[^a-z0-9$]+", " ", spaced).split())
    return (
        bool(tokens & _PRICE_TOKENS)
        and bool(tokens & _UNIT_MODIFIER_TOKENS)
        and not (tokens & _NON_UNIT_MODIFIERS)
    )
