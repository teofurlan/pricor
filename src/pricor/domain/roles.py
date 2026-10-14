"""Closed set of roles a source column can play in a supplier price list."""

from enum import StrEnum


class ColumnRole(StrEnum):
    CODE = "code"
    DESCRIPTION = "description"
    COST_PRICE = "cost_price"
    RETAIL_PRICE = "retail_price"
    VAT_RATE = "vat_rate"
    UNITS_PER_PACK = "units_per_pack"
    BARCODE = "barcode"
    DISCOUNT = "discount"
    CURRENCY = "currency"
    IGNORE = "ignore"
