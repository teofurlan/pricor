"""Import plan model and strict validation of untrusted plan data.

A plan is a recipe written with a closed catalog of operations. It is data,
never code: nothing in this module evaluates or executes anything taken from
the input. `parse_plan` is the only door through which a dict (for example one
proposed by a language model) becomes an `ImportPlan`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from .contract import REQUIRED_FIELDS, TEXT_FIELDS, TargetField
from .parsing import lookup_key

SUPPORTED_CONTRACT_VERSIONS = frozenset({"1"})
DECIMAL_SEPARATORS = frozenset({",", "."})
THOUSANDS_SEPARATORS = frozenset({",", ".", " ", ""})
DISCOUNT_FORMATS = frozenset({"plus_separated"})
ROUNDING_MODES = frozenset({"half_up"})
MAX_ROUNDING_DECIMALS = 8


class Operation(StrEnum):
    PARSE_NUMBER = "parse_number"
    APPLY_DISCOUNTS = "apply_discounts"
    STRIP_VAT = "strip_vat"
    PER_UNIT = "per_unit"
    MAP_VALUES = "map_values"
    CONSTANT = "constant"
    NORMALIZE_TEXT = "normalize_text"


# Fixed execution order of the cost pipeline.
COST_PIPELINE = (
    Operation.PARSE_NUMBER,
    Operation.APPLY_DISCOUNTS,
    Operation.STRIP_VAT,
    Operation.PER_UNIT,
)

_NUMERIC_TARGETS = frozenset(TargetField) - TEXT_FIELDS - {TargetField.UNIT_COST_NET}
_ASSIGNABLE_FIELDS = frozenset(TargetField) - {TargetField.UNIT_COST_NET}
_NORMALIZABLE_FIELDS = frozenset(
    {TargetField.SUPPLIER_CODE, TargetField.DESCRIPTION, TargetField.BARCODE}
)


def column_header(index: int, raw_header: str) -> str:
    """Header a plan uses to reference a column; header-less columns become `column_N`."""
    return raw_header.strip() or f"column_{index}"


class PlanValidationError(Exception):
    """Raised when a plan is invalid. Carries every problem found."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("invalid import plan: " + "; ".join(self.problems))


@dataclass(frozen=True)
class ColumnRef:
    """A source column, always identified by position and header together."""

    index: int
    header: str


@dataclass(frozen=True)
class FromColumn:
    column: ColumnRef


@dataclass(frozen=True)
class FromConstant:
    value: Decimal


@dataclass(frozen=True)
class FromField:
    """Read a value already produced by an earlier step (e.g. vat_rate)."""

    field: TargetField


@dataclass(frozen=True)
class ColumnDiscounts:
    column: ColumnRef
    format: str


@dataclass(frozen=True)
class ConstantDiscounts:
    percents: tuple[Decimal, ...]


@dataclass(frozen=True)
class NormalizeText:
    column: ColumnRef
    to: TargetField
    op = Operation.NORMALIZE_TEXT


@dataclass(frozen=True)
class ParseNumber:
    column: ColumnRef
    decimal_sep: str
    thousands_sep: str
    op = Operation.PARSE_NUMBER


@dataclass(frozen=True)
class ApplyDiscounts:
    source: ColumnDiscounts | ConstantDiscounts
    op = Operation.APPLY_DISCOUNTS


@dataclass(frozen=True)
class StripVat:
    rate_from: FromColumn | FromConstant | FromField
    op = Operation.STRIP_VAT


@dataclass(frozen=True)
class PerUnit:
    units_from: FromColumn | FromConstant
    op = Operation.PER_UNIT


@dataclass(frozen=True)
class MapValues:
    column: ColumnRef
    table: Mapping[str, Decimal | str]
    to: TargetField
    op = Operation.MAP_VALUES


@dataclass(frozen=True)
class Constant:
    field: TargetField
    value: Decimal | str
    op = Operation.CONSTANT


Step = (
    NormalizeText | ParseNumber | ApplyDiscounts | StripVat | PerUnit | MapValues | Constant
)


@dataclass(frozen=True)
class Rounding:
    decimals: int
    mode: str


@dataclass(frozen=True)
class ImportPlan:
    contract_version: str
    engine_version: str
    supplier: str
    steps: tuple[Step, ...]
    rounding: Rounding
    confirmations: tuple[str, ...] = ()


# --- parsing helpers -------------------------------------------------------


class _Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, path: str, message: str) -> None:
        self.items.append(f"{path}: {message}" if path else message)

    def __len__(self) -> int:
        return len(self.items)


def _check_keys(
    obj: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    path: str,
    problems: _Problems,
    noun: str,
) -> bool:
    ok = True
    for key in sorted(required - obj.keys()):
        problems.add(path, f"missing {noun} '{key}'")
        ok = False
    for key in sorted(obj.keys() - required - optional):
        problems.add(path, f"unexpected {noun} '{key}'")
        ok = False
    return ok


def _is_one_of(value: Any, allowed: frozenset[str]) -> bool:
    # Untrusted values may be unhashable (lists, dicts); only strings can match.
    return isinstance(value, str) and value in allowed


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        value = repr(value)
    if isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation:
            return None
        return result if result.is_finite() else None
    return None


def _parse_column(value: Any, path: str, problems: _Problems) -> ColumnRef | None:
    if not isinstance(value, dict):
        problems.add(path, "column reference must be an object with 'index' and 'header'")
        return None
    if not _check_keys(value, {"index", "header"}, set(), path, problems, "key"):
        return None
    index, header = value["index"], value["header"]
    valid = True
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        problems.add(path, "'index' must be a non-negative integer")
        valid = False
    if not isinstance(header, str) or not header.strip():
        problems.add(path, "'header' must be a non-empty string")
        valid = False
    return ColumnRef(index, header) if valid else None


def _parse_field(
    value: Any, allowed: frozenset[TargetField], path: str, problems: _Problems
) -> TargetField | None:
    if isinstance(value, str):
        try:
            field = TargetField(value)
        except ValueError:
            field = None
        if field in allowed:
            return field
    names = ", ".join(sorted(f.value for f in allowed))
    problems.add(path, f"must be one of: {names}")
    return None


def _parse_percent(value: Any, path: str, problems: _Problems) -> Decimal | None:
    number = _to_decimal(value)
    if number is None or not (0 <= number <= 100):
        problems.add(path, "must be a number between 0 and 100")
        return None
    return number


def _parse_value_source(
    value: Any,
    allowed: set[str],
    path: str,
    problems: _Problems,
    *,
    positive: bool = False,
) -> FromColumn | FromConstant | FromField | None:
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value)) not in allowed:
        names = ", ".join(sorted(allowed))
        problems.add(path, f"must be an object with exactly one of: {names}")
        return None
    (kind, raw), = value.items()
    if kind == "column":
        column = _parse_column(raw, f"{path}.column", problems)
        return FromColumn(column) if column else None
    if kind == "field":
        if raw != TargetField.VAT_RATE.value:
            problems.add(f"{path}.field", "only 'vat_rate' can be read from a field")
            return None
        return FromField(TargetField.VAT_RATE)
    number = _to_decimal(raw)
    if number is None or (positive and number <= 0) or (not positive and not 0 <= number <= 100):
        problems.add(
            f"{path}.constant",
            "must be a number greater than 0" if positive else "must be a number between 0 and 100",
        )
        return None
    return FromConstant(number)


# --- step parsers ----------------------------------------------------------


def _parse_normalize_text(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(step, {"column", "to"}, {"op"}, path, problems, "parameter"):
        return None
    column = _parse_column(step["column"], f"{path}.column", problems)
    to = _parse_field(step["to"], _NORMALIZABLE_FIELDS, f"{path}.to", problems)
    return NormalizeText(column, to) if column and to else None


def _parse_parse_number(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(
        step, {"column", "decimal_sep", "thousands_sep"}, {"op"}, path, problems, "parameter"
    ):
        return None
    column = _parse_column(step["column"], f"{path}.column", problems)
    decimal_sep, thousands_sep = step["decimal_sep"], step["thousands_sep"]
    valid = column is not None
    if not _is_one_of(decimal_sep, DECIMAL_SEPARATORS):
        problems.add(f"{path}.decimal_sep", "must be ',' or '.'")
        valid = False
    if not _is_one_of(thousands_sep, THOUSANDS_SEPARATORS):
        problems.add(f"{path}.thousands_sep", "must be one of ',', '.', ' ' or ''")
        valid = False
    if valid and decimal_sep == thousands_sep:
        problems.add(path, "decimal_sep and thousands_sep must differ")
        valid = False
    return ParseNumber(column, decimal_sep, thousands_sep) if valid else None


def _parse_apply_discounts(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(step, {"from"}, {"op"}, path, problems, "parameter"):
        return None
    source = step["from"]
    src_path = f"{path}.from"
    if not isinstance(source, dict):
        problems.add(src_path, "must be an object")
        return None
    if "constant" in source:
        if not _check_keys(source, {"constant"}, set(), src_path, problems, "key"):
            return None
        raw = source["constant"]
        if not isinstance(raw, list) or not raw:
            problems.add(f"{src_path}.constant", "must be a non-empty list of percentages")
            return None
        percents = [
            _parse_percent(item, f"{src_path}.constant[{i}]", problems)
            for i, item in enumerate(raw)
        ]
        if any(p is None for p in percents):
            return None
        return ApplyDiscounts(ConstantDiscounts(tuple(percents)))
    if not _check_keys(source, {"column", "format"}, set(), src_path, problems, "key"):
        return None
    column = _parse_column(source["column"], f"{src_path}.column", problems)
    fmt = source["format"]
    if not _is_one_of(fmt, DISCOUNT_FORMATS):
        problems.add(f"{src_path}.format", "must be 'plus_separated'")
        return None
    return ApplyDiscounts(ColumnDiscounts(column, fmt)) if column else None


def _parse_strip_vat(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(step, {"rate_from"}, {"op"}, path, problems, "parameter"):
        return None
    source = _parse_value_source(
        step["rate_from"], {"column", "constant", "field"}, f"{path}.rate_from", problems
    )
    return StripVat(source) if source else None


def _parse_per_unit(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(step, {"units_from"}, {"op"}, path, problems, "parameter"):
        return None
    source = _parse_value_source(
        step["units_from"], {"column", "constant"}, f"{path}.units_from", problems, positive=True
    )
    return PerUnit(source) if source else None


def _parse_table_value(value: Any, target: TargetField, path: str, problems: _Problems):
    if target in _NUMERIC_TARGETS:
        number = _to_decimal(value)
        if number is None:
            problems.add(path, f"must be a number for field '{target.value}'")
        return number
    if not isinstance(value, str) or not value.strip():
        problems.add(path, f"must be a non-empty string for field '{target.value}'")
        return None
    return value


def _keys_are_distinct(table: Mapping[str, Any], path: str, problems: _Problems) -> bool:
    """The engine looks cells up by `lookup_key`; two keys with the same one would shadow each other."""
    groups: dict[str, list[str]] = {}
    for key in table:
        groups.setdefault(lookup_key(key), []).append(key)
    collisions = [keys for keys in groups.values() if len(keys) > 1]
    for keys in collisions:
        problems.add(path, "keys collide after normalization: " + ", ".join(repr(k) for k in keys))
    return not collisions


def _parse_map_values(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(step, {"column", "table", "to"}, {"op"}, path, problems, "parameter"):
        return None
    column = _parse_column(step["column"], f"{path}.column", problems)
    to = _parse_field(step["to"], _ASSIGNABLE_FIELDS, f"{path}.to", problems)
    raw = step["table"]
    table_path = f"{path}.table"
    if not isinstance(raw, dict) or not raw:
        problems.add(table_path, "must be a non-empty object")
        return None
    if column is None or to is None:
        return None
    table: dict[str, Decimal | str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            problems.add(table_path, "keys must be strings")
            continue
        parsed = _parse_table_value(value, to, f"{table_path}[{key!r}]", problems)
        if parsed is not None:
            table[key] = parsed
    if len(table) != len(raw):
        return None
    if not _keys_are_distinct(table, table_path, problems):
        return None
    return MapValues(column, table, to)


def _parse_constant(step: dict, path: str, problems: _Problems) -> Step | None:
    if not _check_keys(step, {"field", "value"}, {"op"}, path, problems, "parameter"):
        return None
    field = _parse_field(step["field"], _ASSIGNABLE_FIELDS, f"{path}.field", problems)
    if field is None:
        return None
    value = _parse_table_value(step["value"], field, f"{path}.value", problems)
    return Constant(field, value) if value is not None else None


_STEP_PARSERS = {
    Operation.NORMALIZE_TEXT: _parse_normalize_text,
    Operation.PARSE_NUMBER: _parse_parse_number,
    Operation.APPLY_DISCOUNTS: _parse_apply_discounts,
    Operation.STRIP_VAT: _parse_strip_vat,
    Operation.PER_UNIT: _parse_per_unit,
    Operation.MAP_VALUES: _parse_map_values,
    Operation.CONSTANT: _parse_constant,
}


def _parse_step(raw: Any, index: int, problems: _Problems) -> Step | None:
    path = f"steps[{index}]"
    if not isinstance(raw, dict):
        problems.add(path, "must be an object")
        return None
    if "op" not in raw:
        problems.add(path, "missing 'op'")
        return None
    try:
        operation = Operation(raw["op"])
    except ValueError:
        problems.add(path, f"unknown operation {raw['op']!r}")
        return None
    return _STEP_PARSERS[operation](raw, path, problems)


# --- cross-step rules ------------------------------------------------------


def _check_plan_consistency(steps: tuple[Step, ...], problems: _Problems) -> None:
    ranks = [COST_PIPELINE.index(s.op) for s in steps if s.op in COST_PIPELINE]
    if len(ranks) != len(set(ranks)):
        problems.add("steps", "a cost pipeline operation appears more than once")
    elif ranks != sorted(ranks):
        names = " -> ".join(op.value for op in COST_PIPELINE)
        problems.add("steps", f"cost pipeline steps are out of order; required order: {names}")
    if Operation.PARSE_NUMBER not in {s.op for s in steps}:
        problems.add("steps", "plan must include a parse_number step to produce unit_cost_net")

    produced: set[TargetField] = set()
    for i, step in enumerate(steps):
        if isinstance(step, StripVat) and isinstance(step.rate_from, FromField):
            if step.rate_from.field not in produced:
                problems.add(
                    f"steps[{i}].rate_from",
                    "'vat_rate' must be produced by an earlier map_values or constant step",
                )
        if isinstance(step, NormalizeText | MapValues):
            produced.add(step.to)
        elif isinstance(step, Constant):
            produced.add(step.field)

    for field in sorted(REQUIRED_FIELDS - {TargetField.UNIT_COST_NET}):
        if field not in produced:
            problems.add("steps", f"no step produces required field '{field.value}'")


# --- entry point -----------------------------------------------------------


def _parse_rounding(raw: Any, problems: _Problems) -> Rounding | None:
    path = "rounding"
    if not isinstance(raw, dict):
        problems.add(path, "must be an object with 'decimals' and 'mode'")
        return None
    if not _check_keys(raw, {"decimals", "mode"}, set(), path, problems, "key"):
        return None
    decimals, mode = raw["decimals"], raw["mode"]
    valid = True
    if (
        isinstance(decimals, bool)
        or not isinstance(decimals, int)
        or not 0 <= decimals <= MAX_ROUNDING_DECIMALS
    ):
        problems.add(f"{path}.decimals", f"must be an integer between 0 and {MAX_ROUNDING_DECIMALS}")
        valid = False
    if not _is_one_of(mode, ROUNDING_MODES):
        problems.add(f"{path}.mode", "must be 'half_up'")
        valid = False
    return Rounding(decimals, mode) if valid else None


def parse_plan(data: Any) -> ImportPlan:
    """Validate an untrusted dict and build an `ImportPlan`.

    Raises `PlanValidationError` listing every problem found, never just the
    first one.
    """
    problems = _Problems()
    if not isinstance(data, dict):
        raise PlanValidationError(["plan must be an object"])

    _check_keys(
        data,
        {"contract_version", "engine_version", "supplier", "steps", "rounding"},
        {"confirmed_by_user"},
        "",
        problems,
        "key",
    )

    contract_version = data.get("contract_version")
    if "contract_version" in data and not _is_one_of(contract_version, SUPPORTED_CONTRACT_VERSIONS):
        problems.add("contract_version", "unsupported version; supported: 1")
    for key in ("engine_version", "supplier"):
        if key in data and (not isinstance(data[key], str) or not data[key].strip()):
            problems.add(key, "must be a non-empty string")

    confirmations: tuple[str, ...] = ()
    raw_confirmations = data.get("confirmed_by_user", [])
    if not isinstance(raw_confirmations, list) or not all(
        isinstance(c, str) for c in raw_confirmations
    ):
        problems.add("confirmed_by_user", "must be a list of strings")
    else:
        confirmations = tuple(raw_confirmations)

    rounding = _parse_rounding(data["rounding"], problems) if "rounding" in data else None

    steps: list[Step] = []
    raw_steps = data.get("steps")
    if "steps" in data:
        if not isinstance(raw_steps, list) or not raw_steps:
            problems.add("steps", "must be a non-empty list")
        else:
            before = len(problems)
            parsed = [_parse_step(raw, i, problems) for i, raw in enumerate(raw_steps)]
            if len(problems) == before:
                steps = [s for s in parsed if s is not None]
                _check_plan_consistency(tuple(steps), problems)

    if problems.items:
        raise PlanValidationError(problems.items)

    return ImportPlan(
        contract_version=data["contract_version"],
        engine_version=data["engine_version"],
        supplier=data["supplier"],
        steps=tuple(steps),
        rounding=rounding,
        confirmations=confirmations,
    )
