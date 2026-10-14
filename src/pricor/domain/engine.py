"""Deterministic execution of a validated import plan.

The engine never guesses: it checks that the file still has the columns the
plan was written for, runs only the closed catalog of operations, and sorts
every input row into exactly one of two buckets (accepted or rejected with
reasons). All money math uses `Decimal`; rounding happens once, at the end.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Any

from .contract import REQUIRED_FIELDS, ContractRecord, TargetField
from .fx import FxSnapshot, FxSnapshotMismatchError, FxSnapshotRequiredError, MANUAL
from .parsing import (
    CellError,
    lookup_key,
    normalize_text,
    parse_discounts,
    parse_number,
    parse_rate,
    parse_units,
)
from .plan import (
    ApplyDiscounts,
    ColumnDiscounts,
    ColumnRef,
    Constant,
    ConvertCurrency,
    FromColumn,
    FromField,
    ImportPlan,
    MapValues,
    NormalizeText,
    ParseNumber,
    PerUnit,
    StripVat,
    column_header,
)

# Working precision for intermediate results; far beyond any price list.
_CONTEXT = Context(prec=50, rounding=ROUND_HALF_UP)
_HUNDRED = Decimal(100)


class PlanIncompatibleError(Exception):
    """The file no longer matches the plan. Carries every mismatch found."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("plan does not match the file: " + "; ".join(self.problems))


@dataclass(frozen=True)
class TraceStep:
    """Value after one step of the cost pipeline (the first entry is the raw cell)."""

    step: str
    value: Decimal | str


@dataclass(frozen=True)
class AcceptedRow:
    row_number: int
    record: ContractRecord
    trace: tuple[TraceStep, ...]


@dataclass(frozen=True)
class RejectedRow:
    row_number: int
    cells: tuple[Any, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    accepted: tuple[AcceptedRow, ...]
    rejected: tuple[RejectedRow, ...]


def _conversion_step(plan: ImportPlan, fx: FxSnapshot | None) -> ConvertCurrency | None:
    """The plan's conversion, once the run's snapshot is known to fit it."""
    step = next((item for item in plan.steps if isinstance(item, ConvertCurrency)), None)
    if step is None:
        return None
    if fx is None:
        raise FxSnapshotRequiredError(
            f"the plan converts {step.from_currency} to {step.to_currency} "
            f"({step.rate_type}, {step.side}) and the run has no exchange rate"
        )
    if (fx.from_currency, fx.to_currency) != (step.from_currency, step.to_currency) or (
        fx.rate_type not in (step.rate_type, MANUAL) or fx.side != step.side
    ):
        raise FxSnapshotMismatchError(
            f"the plan needs {step.from_currency}->{step.to_currency} {step.rate_type}/{step.side} "
            f"but the snapshot is {fx.from_currency}->{fx.to_currency} {fx.rate_type}/{fx.side}"
        )
    return step


def _normalize_header(header: str) -> str:
    return " ".join(header.split()).casefold()


def _referenced_columns(plan: ImportPlan) -> list[ColumnRef]:
    refs: list[ColumnRef] = []
    for step in plan.steps:
        if isinstance(step, NormalizeText | ParseNumber | MapValues):
            refs.append(step.column)
        elif isinstance(step, ApplyDiscounts) and isinstance(step.source, ColumnDiscounts):
            refs.append(step.source.column)
        elif isinstance(step, StripVat) and isinstance(step.rate_from, FromColumn):
            refs.append(step.rate_from.column)
        elif isinstance(step, PerUnit) and isinstance(step.units_from, FromColumn):
            refs.append(step.units_from.column)
    return refs


def check_compatibility(plan: ImportPlan, headers: Sequence[str]) -> None:
    """Raise `PlanIncompatibleError` if any referenced column moved or was renamed."""
    problems: list[str] = []
    seen: set[tuple[int, str]] = set()
    for ref in _referenced_columns(plan):
        if (ref.index, ref.header) in seen:
            continue
        seen.add((ref.index, ref.header))
        if ref.index >= len(headers):
            problems.append(
                f"column {ref.index} ('{ref.header}') does not exist; "
                f"the file has {len(headers)} columns"
            )
        elif _normalize_header(column_header(ref.index, str(headers[ref.index]))) != (
            _normalize_header(ref.header)
        ):
            problems.append(
                f"column {ref.index} is '{headers[ref.index]}' in the file "
                f"but the plan expects '{ref.header}'"
            )
    if problems:
        raise PlanIncompatibleError(problems)


def _cell(row: Sequence[Any], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    value = row[index]
    return value if isinstance(value, str) else str(value)


def _native_number(row: Sequence[Any], index: int) -> Decimal | None:
    """Return a cell that is already numeric (e.g. from XLSX) as an exact Decimal.

    Such cells carry no locale formatting, so the plan's separators do not apply.
    """
    if index >= len(row):
        return None
    value = row[index]
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal) and value.is_finite():
        return value
    if isinstance(value, int | float):
        number = Decimal(repr(value))
        return number if number.is_finite() else None
    return None


class _RowRun:
    """Executes the plan over one row, collecting values, trace and reasons."""

    def __init__(
        self,
        plan: ImportPlan,
        tables: dict[int, dict[str, Decimal | str]],
        row,
        conversion: ConvertCurrency | None = None,
        fx: FxSnapshot | None = None,
    ):
        self.plan = plan
        self.tables = tables
        self.row = row
        self.conversion = conversion
        self.fx = fx
        self.converted: Decimal | None = None
        self.fields: dict[TargetField, Decimal | str] = {}
        self.failed: set[TargetField] = set()
        self.reasons: list[str] = []
        self.trace: list[TraceStep] = []
        self.cost: Decimal | None = None
        self.cost_broken = False

    # -- helpers --

    def _reject(self, ref: ColumnRef | None, message: str, field: TargetField | None = None):
        prefix = f"{ref.header}: " if ref else ""
        self.reasons.append(prefix + message)
        if field is not None:
            self.failed.add(field)

    def _break_cost(self) -> None:
        self.cost_broken = True
        self.failed.add(TargetField.UNIT_COST_NET)

    def _advance(self, name: str, value: Decimal) -> None:
        self.cost = value
        self.trace.append(TraceStep(name, value))

    # -- operations --

    def run(self) -> None:
        for index, step in enumerate(self.plan.steps):
            try:
                self._execute(index, step)
            except ArithmeticError as error:
                self._reject(None, f"arithmetic error in {step.op.value}: {error}")
                self._break_cost()
        self._finish()

    def _execute(self, index: int, step) -> None:
        if isinstance(step, NormalizeText):
            self._normalize_text(step)
        elif isinstance(step, ParseNumber):
            self._parse_number(step)
        elif isinstance(step, ApplyDiscounts):
            self._apply_discounts(step)
        elif isinstance(step, StripVat):
            self._strip_vat(step)
        elif isinstance(step, PerUnit):
            self._per_unit(step)
        elif isinstance(step, MapValues):
            self._map_values(index, step)
        elif isinstance(step, Constant):
            self.fields[step.field] = step.value

    def _normalize_text(self, step: NormalizeText) -> None:
        text = normalize_text(_cell(self.row, step.column.index))
        if text:
            self.fields[step.to] = text
        elif step.to is not TargetField.BARCODE:
            self._reject(step.column, f"{step.to.value} is empty", step.to)

    def _parse_number(self, step: ParseNumber) -> None:
        raw = _cell(self.row, step.column.index)
        self.trace.append(TraceStep("original", raw))
        try:
            native = _native_number(self.row, step.column.index)
            self.cost = (
                native
                if native is not None
                else parse_number(raw, step.decimal_sep, step.thousands_sep)
            )
        except CellError as error:
            self._reject(step.column, str(error))
            self._break_cost()
            return
        self.trace.append(TraceStep("parse_number", self.cost))

    def _apply_discounts(self, step: ApplyDiscounts) -> None:
        source = step.source
        try:
            if isinstance(source, ColumnDiscounts):
                percents = parse_discounts(_cell(self.row, source.column.index))
            else:
                percents = source.percents
        except CellError as error:
            ref = source.column if isinstance(source, ColumnDiscounts) else None
            self._reject(ref, str(error))
            self._break_cost()
            return
        if self.cost_broken:
            return
        value = self.cost
        for percent in percents:
            factor = _CONTEXT.divide(_CONTEXT.subtract(_HUNDRED, percent), _HUNDRED)
            value = _CONTEXT.multiply(value, factor)
        self._advance("apply_discounts", value)

    def _strip_vat(self, step: StripVat) -> None:
        source = step.rate_from
        try:
            if isinstance(source, FromColumn):
                rate = parse_rate(_cell(self.row, source.column.index))
            elif isinstance(source, FromField):
                if TargetField.VAT_RATE in self.failed:
                    self._break_cost()  # reason already recorded by the producing step
                    return
                rate = self.fields.get(TargetField.VAT_RATE)
                if not isinstance(rate, Decimal):
                    raise CellError("vat_rate is not available")
            else:
                rate = source.value
        except CellError as error:
            ref = source.column if isinstance(source, FromColumn) else None
            self._reject(ref, str(error))
            self._break_cost()
            return
        if self.cost_broken:
            return
        divisor = _CONTEXT.add(Decimal(1), _CONTEXT.divide(rate, _HUNDRED))
        self._advance("strip_vat", _CONTEXT.divide(self.cost, divisor))

    def _per_unit(self, step: PerUnit) -> None:
        source = step.units_from
        try:
            if isinstance(source, FromColumn):
                units = parse_units(_cell(self.row, source.column.index))
            else:
                units = source.value
        except CellError as error:
            ref = source.column if isinstance(source, FromColumn) else None
            self._reject(ref, str(error))
            self._break_cost()
            return
        if self.cost_broken:
            return
        self.fields.setdefault(TargetField.UNITS_PER_PACK, units)
        self._advance("per_unit", _CONTEXT.divide(self.cost, units))

    def _map_values(self, index: int, step: MapValues) -> None:
        key = normalize_text(_cell(self.row, step.column.index))
        table = self.tables[index]
        if lookup_key(key) not in table:
            self._reject(step.column, f"unmapped value {key!r}", step.to)
            return
        self.fields[step.to] = table[lookup_key(key)]

    # -- closing checks --

    def _finish(self) -> None:
        for field in sorted(REQUIRED_FIELDS - {TargetField.UNIT_COST_NET}):
            if field not in self.failed and field not in self.fields:
                self._reject(None, f"required field {field.value} is missing")
        if not self.cost_broken and self.cost is not None:
            if self.cost < 0:
                self._reject(None, f"negative unit cost: {self.cost}")
            else:
                self._round()

    def _round(self) -> None:
        quantum = Decimal(1).scaleb(-self.plan.rounding.decimals)
        unrounded = self.cost
        try:
            rounded = self.cost.quantize(quantum, rounding=ROUND_HALF_UP, context=_CONTEXT)
        except ArithmeticError:
            self._reject(None, "unit cost out of range")
            return
        self.cost = rounded
        self.trace.append(TraceStep("rounding", rounded))
        self._convert(unrounded, quantum)

    def _convert(self, unrounded: Decimal, quantum: Decimal) -> None:
        """The converted cost comes from the unrounded one, so rounding still happens once."""
        step = self.conversion
        if step is None:
            return
        currency = str(self.fields.get(TargetField.CURRENCY, "")).upper()
        if currency == step.to_currency:
            return  # already in the target currency
        if currency != step.from_currency:
            self._reject(
                None,
                f"currency {currency} cannot be converted: "
                f"the plan converts {step.from_currency} to {step.to_currency}",
            )
            return
        try:
            converted = _CONTEXT.multiply(unrounded, self.fx.rate).quantize(
                quantum, rounding=ROUND_HALF_UP, context=_CONTEXT
            )
        except ArithmeticError:
            self._reject(None, "converted unit cost out of range")
            return
        self.converted = converted
        self.trace.append(TraceStep("convert_currency", converted))

    def record(self) -> ContractRecord:
        get = self.fields.get
        return ContractRecord(
            supplier_code=get(TargetField.SUPPLIER_CODE),
            description=get(TargetField.DESCRIPTION),
            unit_cost_net=self.cost,
            currency=get(TargetField.CURRENCY),
            vat_rate=get(TargetField.VAT_RATE),
            units_per_pack=get(TargetField.UNITS_PER_PACK),
            barcode=get(TargetField.BARCODE),
            suggested_retail_price=get(TargetField.SUGGESTED_RETAIL_PRICE),
            unit_cost_net_converted=self.converted,
            fx_rate=None if self.converted is None else self.fx.rate,
            fx_source=None if self.converted is None else self.fx.label,
            fx_date=None if self.converted is None else self.fx.date,
        )


def _normalized_tables(plan: ImportPlan) -> dict[int, dict[str, Decimal | str]]:
    return {
        index: {lookup_key(key): value for key, value in step.table.items()}
        for index, step in enumerate(plan.steps)
        if isinstance(step, MapValues)
    }


def execute_numbered_rows(
    plan: ImportPlan,
    headers: Sequence[str],
    numbered_rows: Iterable[tuple[int, Sequence[Any]]],
    fx: FxSnapshot | None = None,
) -> ImportResult:
    """Run `plan` over `(row_number, row)` pairs, which need not be contiguous.

    This is the shape the profiler's `engine_input` returns: only data rows,
    each carrying its real file row number. Every pair ends up accepted or
    rejected under that same number.

    `fx` is the run's exchange-rate snapshot. A plan that converts currency refuses to run
    without a fitting one (`FxSnapshotRequiredError`, `FxSnapshotMismatchError`); a plan that
    does not convert ignores it.

    Raises `PlanIncompatibleError` before touching any row if the headers no
    longer match the plan.
    """
    check_compatibility(plan, headers)
    conversion = _conversion_step(plan, fx)
    tables = _normalized_tables(plan)

    accepted: list[AcceptedRow] = []
    rejected: list[RejectedRow] = []
    for number, row in numbered_rows:
        run = _RowRun(plan, tables, row, conversion, fx)
        run.run()
        if run.reasons:
            rejected.append(RejectedRow(number, tuple(row), tuple(run.reasons)))
        else:
            accepted.append(AcceptedRow(number, run.record(), tuple(run.trace)))
    return ImportResult(tuple(accepted), tuple(rejected))


def execute_plan(
    plan: ImportPlan,
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    first_row_number: int = 1,
    fx: FxSnapshot | None = None,
) -> ImportResult:
    """Run `plan` over contiguous `rows` numbered from `first_row_number`."""
    return execute_numbered_rows(
        plan, headers, ((first_row_number + offset, row) for offset, row in enumerate(rows)), fx
    )
