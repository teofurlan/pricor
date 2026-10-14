"""Which column role each source column plays in a saved plan.

A plan only references the columns it uses, but reusing it for the supplier's
next file means knowing what every used column *was for*. The role is read back
from the steps, the inverse of what `plan_builder` writes.
"""

from .contract import TargetField
from .plan import (
    ApplyDiscounts,
    ColumnDiscounts,
    ColumnRef,
    FromColumn,
    ImportPlan,
    MapValues,
    NormalizeText,
    ParseNumber,
    PerUnit,
    StripVat,
)
from .roles import ColumnRole

_NORMALIZED_ROLES = {
    TargetField.SUPPLIER_CODE: ColumnRole.CODE,
    TargetField.DESCRIPTION: ColumnRole.DESCRIPTION,
    TargetField.BARCODE: ColumnRole.BARCODE,
}
_MAPPED_ROLES = {
    TargetField.VAT_RATE: ColumnRole.VAT_RATE,
    TargetField.CURRENCY: ColumnRole.CURRENCY,
    TargetField.UNITS_PER_PACK: ColumnRole.UNITS_PER_PACK,
}


def _used(step) -> tuple[ColumnRef, ColumnRole] | None:
    match step:
        case NormalizeText(column=column, to=field) if field in _NORMALIZED_ROLES:
            return column, _NORMALIZED_ROLES[field]
        case ParseNumber(column=column):
            return column, ColumnRole.COST_PRICE
        case ApplyDiscounts(source=ColumnDiscounts(column=column)):
            return column, ColumnRole.DISCOUNT
        case StripVat(rate_from=FromColumn(column=column)):
            return column, ColumnRole.VAT_RATE
        case PerUnit(units_from=FromColumn(column=column)):
            return column, ColumnRole.UNITS_PER_PACK
        case MapValues(column=column, to=field) if field in _MAPPED_ROLES:
            return column, _MAPPED_ROLES[field]
    return None


def column_roles(plan: ImportPlan) -> dict[int, ColumnRole]:
    """Source column index -> the role it plays in `plan`. The first step to use a column wins."""
    roles: dict[int, ColumnRole] = {}
    for step in plan.steps:
        used = _used(step)
        if used is not None:
            roles.setdefault(used[0].index, used[1])
    return roles
