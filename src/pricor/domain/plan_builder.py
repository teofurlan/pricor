"""Deterministic plan builder: column roles + confirmed parameters -> `ImportPlan`.

A model may hypothesise parameters and ask questions, but it never writes the
plan. This module assembles the plan dict in the fixed catalog order from facts
(which column plays which role, what the profiler measured) and from
parameters the user confirmed, then hands it to `parse_plan`, the single door
through which a plan becomes valid. When a required parameter is still
unknown the builder returns it as *unresolved* instead of choosing a default.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pricor import __version__

from .fx import DEFAULT_SIDE, TARGET_CURRENCY
from .parsing import lookup_key
from .plan import ImportPlan, column_header, parse_plan
from .profile import ColumnProfile
from .roles import ColumnRole

CONTRACT_VERSION = "1"
ROUNDING_DECIMALS = 2


@dataclass(frozen=True)
class RoleAssignment:
    """A column of the profiled sheet together with the role chosen for it."""

    column: ColumnProfile
    role: ColumnRole


@dataclass(frozen=True)
class ColumnSource:
    """Read the value from the column that plays the matching role.

    `value_map` translates the column's text into the target value (VAT rates
    such as ``"21%"`` -> ``21``, or currency names -> ISO codes).
    """

    value_map: Mapping[str, Decimal | str] | None = None


@dataclass(frozen=True)
class ConstantSource:
    """The same value for every row (a rate, a unit count, a currency, discounts)."""

    value: Any


@dataclass(frozen=True)
class FxChoice:
    """Convert foreign prices to pesos with this rate type and side (`manual` = typed per run)."""

    rate_type: str
    side: str = DEFAULT_SIDE


@dataclass(frozen=True)
class KeepOriginalCurrency:
    """The user chose not to convert: costs stay in the supplier's currency."""


@dataclass(frozen=True)
class PlanParameters:
    """What the model may hypothesise and the user confirms. `None` means unknown.

    A source left as `None` means "no override": the builder uses the column
    that plays the matching role if there is one, and omits the step if not.
    The semantic questions (`price_includes_vat`, `price_is_per_pack`,
    `currency`) are never defaulted.
    """

    supplier: str
    price_includes_vat: bool | None = None
    price_is_per_pack: bool | None = None
    vat_source: ColumnSource | ConstantSource | None = None
    units_source: ColumnSource | ConstantSource | None = None
    discounts: ColumnSource | ConstantSource | None = None
    currency: ColumnSource | ConstantSource | None = None
    decimal_sep: str | None = None
    thousands_sep: str | None = None
    fx: FxChoice | KeepOriginalCurrency | None = None
    confirmations: Sequence[str] = ()


@dataclass(frozen=True)
class UnresolvedParameter:
    """A parameter the plan cannot be built without, and why."""

    parameter: str
    reason: str


@dataclass(frozen=True)
class PlanBuild:
    """Either a valid plan or the parameters that are still unresolved."""

    plan: ImportPlan | None
    unresolved: tuple[UnresolvedParameter, ...] = field(default=())


def _ref(column: ColumnProfile) -> dict[str, Any]:
    return {"index": column.index, "header": column_header(column.index, column.raw_header)}


def _single(
    columns: list[ColumnProfile], parameter: str, label: str, missing: list[UnresolvedParameter]
) -> ColumnProfile | None:
    if len(columns) == 1:
        return columns[0]
    reason = (
        f"no column was identified as {label}"
        if not columns
        else f"{len(columns)} columns were identified as {label}; exactly one is needed"
    )
    missing.append(UnresolvedParameter(parameter, reason))
    return None


def _separators(
    column: ColumnProfile | None, parameters: PlanParameters, missing: list[UnresolvedParameter]
) -> tuple[str, str] | None:
    if parameters.decimal_sep is not None and parameters.thousands_sep is not None:
        return parameters.decimal_sep, parameters.thousands_sep
    if column is None:
        return None
    fmt = column.number_format
    if fmt is None:
        missing.append(
            UnresolvedParameter(
                "number_format",
                f"column '{column.plan_header}' does not read as numbers, "
                "so its decimal and thousands separators are unknown",
            )
        )
        return None
    if fmt.ambiguous:
        missing.append(UnresolvedParameter("number_format", fmt.evidence))
        return None
    if fmt.decimal_sep is not None:
        return fmt.decimal_sep, fmt.thousands_sep or ""
    # The profiler saw numbers and no separator in any of them, so either convention reads
    # them the same.
    return ".", ""


def build_plan(assignments: Sequence[RoleAssignment], parameters: PlanParameters) -> PlanBuild:
    """Assemble and validate a plan, or report which parameters are unresolved."""
    by_role: dict[ColumnRole, list[ColumnProfile]] = {role: [] for role in ColumnRole}
    for item in assignments:
        by_role[item.role].append(item.column)

    missing: list[UnresolvedParameter] = []
    code = _single(by_role[ColumnRole.CODE], "code_column", "the product code", missing)
    description = _single(
        by_role[ColumnRole.DESCRIPTION], "description_column", "the description", missing
    )
    cost = _single(by_role[ColumnRole.COST_PRICE], "cost_price_column", "the cost price", missing)
    barcodes = by_role[ColumnRole.BARCODE]
    if len(barcodes) > 1:
        missing.append(
            UnresolvedParameter(
                "barcode_column", f"{len(barcodes)} columns were identified as the barcode"
            )
        )
    vat_column = _first(by_role[ColumnRole.VAT_RATE])
    units_column = _first(by_role[ColumnRole.UNITS_PER_PACK])
    discount_column = _first(by_role[ColumnRole.DISCOUNT])
    currency_column = _first(by_role[ColumnRole.CURRENCY])

    separators = _separators(cost, parameters, missing)

    steps: list[dict[str, Any]] = []
    if code and description:
        steps.append({"op": "normalize_text", "column": _ref(code), "to": "supplier_code"})
        steps.append({"op": "normalize_text", "column": _ref(description), "to": "description"})
    if len(barcodes) == 1:
        steps.append({"op": "normalize_text", "column": _ref(barcodes[0]), "to": "barcode"})
    if cost and separators:
        steps.append(
            {
                "op": "parse_number",
                "column": _ref(cost),
                "decimal_sep": separators[0],
                "thousands_sep": separators[1],
            }
        )

    _discount_step(steps, parameters.discounts, discount_column)
    _vat_steps(steps, parameters, vat_column, missing)
    _per_unit_step(steps, parameters, units_column, missing)
    currencies = _currency_step(steps, parameters.currency, currency_column, missing)
    _fx_step(steps, parameters.fx, currencies, missing)

    if missing:
        return PlanBuild(None, tuple(missing))

    plan = parse_plan(
        {
            "contract_version": CONTRACT_VERSION,
            "engine_version": __version__,
            "supplier": parameters.supplier,
            "steps": steps,
            "rounding": {"decimals": ROUNDING_DECIMALS, "mode": "half_up"},
            "confirmed_by_user": list(parameters.confirmations),
        }
    )
    return PlanBuild(plan)


def _first(columns: list[ColumnProfile]) -> ColumnProfile | None:
    return columns[0] if columns else None


def _table(value_map: Mapping[str, Decimal | str]) -> dict[str, Any]:
    return dict(value_map)


def _discount_step(
    steps: list[dict[str, Any]],
    source: ColumnSource | ConstantSource | None,
    column: ColumnProfile | None,
) -> None:
    if isinstance(source, ConstantSource):
        # An empty constant is an explicit "no discounts": omit the step.
        if source.value:
            steps.append(
                {"op": "apply_discounts", "from": {"constant": [str(p) for p in source.value]}}
            )
    elif column is not None:
        steps.append(
            {
                "op": "apply_discounts",
                "from": {"column": _ref(column), "format": "plus_separated"},
            }
        )


def _vat_steps(
    steps: list[dict[str, Any]],
    parameters: PlanParameters,
    column: ColumnProfile | None,
    missing: list[UnresolvedParameter],
) -> None:
    if parameters.price_includes_vat is None:
        missing.append(
            UnresolvedParameter(
                "price_includes_vat", "it is not known whether the cost price includes VAT"
            )
        )
        return
    if not parameters.price_includes_vat:
        return
    source = parameters.vat_source
    if isinstance(source, ConstantSource):
        steps.append({"op": "strip_vat", "rate_from": {"constant": str(source.value)}})
    elif column is None:
        missing.append(
            UnresolvedParameter(
                "vat_rate", "prices include VAT but there is no VAT column or constant rate"
            )
        )
    elif isinstance(source, ColumnSource) and source.value_map:
        steps.append(
            {
                "op": "map_values",
                "column": _ref(column),
                "table": {key: str(value) for key, value in source.value_map.items()},
                "to": "vat_rate",
            }
        )
        steps.append({"op": "strip_vat", "rate_from": {"field": "vat_rate"}})
    else:
        steps.append({"op": "strip_vat", "rate_from": {"column": _ref(column)}})


def _per_unit_step(
    steps: list[dict[str, Any]],
    parameters: PlanParameters,
    column: ColumnProfile | None,
    missing: list[UnresolvedParameter],
) -> None:
    source = parameters.units_source
    has_source = isinstance(source, ConstantSource) or column is not None
    if parameters.price_is_per_pack is None:
        if has_source:
            missing.append(
                UnresolvedParameter(
                    "price_is_per_pack",
                    "a units-per-pack source exists but it is not known whether the price is per pack",
                )
            )
        return
    if not parameters.price_is_per_pack:
        return
    if isinstance(source, ConstantSource):
        steps.append({"op": "per_unit", "units_from": {"constant": str(source.value)}})
    elif column is not None:
        steps.append({"op": "per_unit", "units_from": {"column": _ref(column)}})
    else:
        missing.append(
            UnresolvedParameter(
                "units_per_pack", "the price is per pack but no units-per-pack source is known"
            )
        )


_CURRENCY_NAMES = {
    "ARS": ("$", "ars", "$ars", "peso", "pesos", "peso argentino", "pesos argentinos"),
    "USD": (
        "u$s",
        "us$",
        "u$d",
        "u$",
        "usd",
        "dolar",
        "dolares",
        "dólar",
        "dólares",
        "dolar estadounidense",
        "dolares estadounidenses",
    ),
    "EUR": ("eur", "€", "euro", "euros"),
}
_CURRENCY_BY_NAME = {name: code for code, names in _CURRENCY_NAMES.items() for name in names}
_COMPLETE_SAMPLES_BELOW = 5  # the profiler lists every distinct value only below this many


def _currency_key(text: str) -> str:
    return lookup_key(text).replace(".", "")


def infer_currency_map(column: ColumnProfile) -> dict[str, str] | None:
    """Read a currency column's values as ISO codes, only when every value is recognized.

    `$` is pesos, `u$s` or `usd` dollars, and so on. Anything unknown, or a column with more
    distinct values than the profiler listed, returns `None` so the user is asked instead.
    """
    if not column.samples or len(column.samples) >= _COMPLETE_SAMPLES_BELOW:
        return None
    table: dict[str, str] = {}
    for sample in column.samples:
        code = _CURRENCY_BY_NAME.get(_currency_key(sample))
        if code is None:
            return None
        table.setdefault(lookup_key(sample), code)
    return table


def _currency_step(
    steps: list[dict[str, Any]],
    source: ColumnSource | ConstantSource | None,
    column: ColumnProfile | None,
    missing: list[UnresolvedParameter],
) -> set[str] | None:
    """Add the step that sets the currency; return the currencies it can produce, if known."""
    if source is None and column is not None:
        inferred = infer_currency_map(column)
        if inferred is not None:
            source = ColumnSource(inferred)
    if isinstance(source, ConstantSource):
        steps.append({"op": "constant", "field": "currency", "value": str(source.value)})
        return {str(source.value)}
    if isinstance(source, ColumnSource) and source.value_map and column is not None:
        steps.append(
            {
                "op": "map_values",
                "column": _ref(column),
                "table": _table(source.value_map),
                "to": "currency",
            }
        )
        return {str(value) for value in source.value_map.values()}
    if column is not None:
        missing.append(
            UnresolvedParameter(
                "currency", "a currency column exists but its values are not mapped to ISO codes"
            )
        )
    else:
        missing.append(UnresolvedParameter("currency", "the currency of the prices is not known"))
    return None


def _fx_step(
    steps: list[dict[str, Any]],
    choice: FxChoice | KeepOriginalCurrency | None,
    currencies: set[str] | None,
    missing: list[UnresolvedParameter],
) -> None:
    """Conversion to pesos, asked only when the prices include a foreign currency."""
    foreign = sorted((currencies or set()) - {TARGET_CURRENCY})
    if not foreign:
        return
    if choice is None:
        missing.append(
            UnresolvedParameter(
                "fx_conversion",
                f"the prices include {', '.join(foreign)}; "
                f"it is not known whether to convert them to {TARGET_CURRENCY}",
            )
        )
    elif isinstance(choice, FxChoice):
        if len(foreign) > 1:
            missing.append(
                UnresolvedParameter(
                    "fx_currencies",
                    f"the prices include {', '.join(foreign)}; "
                    "one exchange rate cannot convert more than one currency",
                )
            )
            return
        steps.append(
            {
                "op": "convert_currency",
                "from": foreign[0],
                "to": TARGET_CURRENCY,
                "rate_type": choice.rate_type,
                "side": choice.side,
            }
        )
