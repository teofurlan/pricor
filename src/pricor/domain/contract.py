"""Target contract: the normalized shape every supplier row is converted to."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class TargetField(StrEnum):
    SUPPLIER_CODE = "supplier_code"
    DESCRIPTION = "description"
    UNIT_COST_NET = "unit_cost_net"
    CURRENCY = "currency"
    VAT_RATE = "vat_rate"
    UNITS_PER_PACK = "units_per_pack"
    BARCODE = "barcode"
    SUGGESTED_RETAIL_PRICE = "suggested_retail_price"


REQUIRED_FIELDS = frozenset(
    {
        TargetField.SUPPLIER_CODE,
        TargetField.DESCRIPTION,
        TargetField.UNIT_COST_NET,
        TargetField.CURRENCY,
    }
)

OPTIONAL_FIELDS = frozenset(
    {
        TargetField.VAT_RATE,
        TargetField.UNITS_PER_PACK,
        TargetField.BARCODE,
        TargetField.SUGGESTED_RETAIL_PRICE,
    }
)

# Fields that hold text. Codes and barcodes must never be coerced to numbers,
# otherwise leading zeros are lost.
TEXT_FIELDS = frozenset(
    {
        TargetField.SUPPLIER_CODE,
        TargetField.DESCRIPTION,
        TargetField.CURRENCY,
        TargetField.BARCODE,
    }
)


@dataclass(frozen=True)
class ContractRecord:
    """One normalized product row. Money fields are Decimal, never float."""

    supplier_code: str
    description: str
    unit_cost_net: Decimal
    currency: str
    vat_rate: Decimal | None = None
    units_per_pack: Decimal | None = None
    barcode: str | None = None
    suggested_retail_price: Decimal | None = None
    # Filled only when the plan converts currency and the row is in the source currency.
    # `unit_cost_net` and `currency` always keep the supplier's own values.
    unit_cost_net_converted: Decimal | None = None
    fx_rate: Decimal | None = None
    fx_source: str | None = None
    fx_date: str | None = None  # ISO date of the quote
