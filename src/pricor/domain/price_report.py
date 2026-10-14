"""Price-change report: what moved between two consecutive price lists of one supplier.

Products are matched by `supplier_code` (trimmed, whitespace collapsed, case-folded) and
costs are compared in the currency each record was imported in: nothing is ever converted.
All arithmetic is exact `Decimal`; the only rounding is `percent_text`, for display.

Rules worth knowing:

* An *anomaly* is a change whose size is strictly beyond the threshold, a ratio of the
  previous cost (default 0.30 = 30%): `|current - previous| > threshold * |previous|`. A
  change of exactly the threshold is not an anomaly.
* A cost that goes from zero to something has no meaningful percentage, so it is its own
  section (`from_zero`), always counted as an anomaly, and never divided.
* The same code with a different currency is reported in `currency_changed`, with no
  percentage, and is not an increase or a decrease.
* A code that appears more than once within one list cannot be matched with confidence, so
  it is left out of every other section and listed in `ambiguous_codes` instead.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from .contract import ContractRecord
from .parsing import lookup_key

DEFAULT_ANOMALY_THRESHOLD = Decimal("0.30")
_PRECISION = 60  # digits of working precision: far beyond any price a supplier writes
_PERCENT_PLACES = Decimal("0.01")
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class PriceChange:
    supplier_code: str
    description: str  # as in the current list
    currency: str
    previous_cost: Decimal
    current_cost: Decimal
    change: Decimal  # current - previous, in `currency`
    change_ratio: Decimal | None  # change / |previous|; `None` when the previous cost is zero
    anomaly: bool


@dataclass(frozen=True)
class ProductPrice:
    supplier_code: str
    description: str
    currency: str
    unit_cost_net: Decimal


@dataclass(frozen=True)
class CurrencyChange:
    supplier_code: str
    description: str
    previous_currency: str
    current_currency: str
    previous_cost: Decimal
    current_cost: Decimal


@dataclass(frozen=True)
class AmbiguousCode:
    supplier_code: str
    previous_count: int
    current_count: int


@dataclass(frozen=True)
class ReportSummary:
    unchanged: int
    increases: int
    decreases: int
    from_zero: int
    new_products: int
    discontinued: int
    currency_changed: int
    ambiguous: int
    anomalies: int
    median_change: Decimal | None  # ratio; of the increases and decreases only


@dataclass(frozen=True)
class PriceReport:
    threshold: Decimal
    increases: tuple[PriceChange, ...]
    decreases: tuple[PriceChange, ...]
    from_zero: tuple[PriceChange, ...]
    new_products: tuple[ProductPrice, ...]
    discontinued: tuple[ProductPrice, ...]
    currency_changed: tuple[CurrencyChange, ...]
    ambiguous_codes: tuple[AmbiguousCode, ...]
    unchanged_count: int
    anomalies: tuple[PriceChange, ...]
    summary: ReportSummary


def percent_text(ratio: Decimal) -> str:
    """A ratio as a percentage with two decimals, rounded half away from zero (display only)."""
    with localcontext() as context:
        context.prec = _PRECISION
        rounded = (ratio * _HUNDRED).quantize(_PERCENT_PLACES, rounding=ROUND_HALF_UP)
    return format(abs(rounded) if rounded.is_zero() else rounded, "f")


def _group(records: Iterable[ContractRecord]) -> dict[str, list[ContractRecord]]:
    groups: dict[str, list[ContractRecord]] = {}
    for record in records:
        groups.setdefault(lookup_key(record.supplier_code), []).append(record)
    return groups


def _currency(record: ContractRecord) -> str:
    return record.currency.strip().upper()


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    with localcontext() as context:
        context.prec = _PRECISION
        return (ordered[middle - 1] + ordered[middle]) / 2


def _change(before: ContractRecord, after: ContractRecord, threshold: Decimal) -> PriceChange:
    with localcontext() as context:
        context.prec = _PRECISION
        change = after.unit_cost_net - before.unit_cost_net
        base = abs(before.unit_cost_net)
        if base.is_zero():
            ratio, anomaly = None, True
        else:
            ratio, anomaly = change / base, abs(change) > threshold * base
    return PriceChange(
        after.supplier_code,
        after.description,
        _currency(after),
        before.unit_cost_net,
        after.unit_cost_net,
        change,
        ratio,
        anomaly,
    )


def compare_price_lists(
    previous_records: Sequence[ContractRecord],
    current_records: Sequence[ContractRecord],
    threshold: Decimal = DEFAULT_ANOMALY_THRESHOLD,
) -> PriceReport:
    """Compare two imports of the same supplier, `previous_records` being the older one."""
    if not threshold.is_finite() or threshold < 0:
        raise ValueError(f"threshold must be a finite ratio of zero or more, got {threshold}")
    before, after = _group(previous_records), _group(current_records)

    ambiguous = tuple(
        AmbiguousCode(
            (before.get(key) or after[key])[0].supplier_code,
            len(before.get(key, ())),
            len(after.get(key, ())),
        )
        for key in sorted(before.keys() | after.keys())
        if len(before.get(key, ())) > 1 or len(after.get(key, ())) > 1
    )
    left_out = {lookup_key(item.supplier_code) for item in ambiguous}

    changes: list[tuple[str, PriceChange]] = []
    currency_changed: list[tuple[str, CurrencyChange]] = []
    unchanged = 0
    for key in sorted((before.keys() & after.keys()) - left_out):
        old, new = before[key][0], after[key][0]
        if _currency(old) != _currency(new):
            currency_changed.append(
                (
                    key,
                    CurrencyChange(
                        new.supplier_code,
                        new.description,
                        _currency(old),
                        _currency(new),
                        old.unit_cost_net,
                        new.unit_cost_net,
                    ),
                )
            )
        elif old.unit_cost_net == new.unit_cost_net:
            unchanged += 1
        else:
            changes.append((key, _change(old, new, threshold)))

    def priced(records: dict[str, list[ContractRecord]], keys: Iterable[str]):
        return tuple(
            ProductPrice(item.supplier_code, item.description, _currency(item), item.unit_cost_net)
            for item in (records[key][0] for key in sorted(keys))
        )

    increases = tuple(
        change
        for _, change in sorted(
            (pair for pair in changes if pair[1].change_ratio is not None and pair[1].change_ratio > 0),
            key=lambda pair: (-pair[1].change_ratio, pair[0]),
        )
    )
    decreases = tuple(
        change
        for _, change in sorted(
            (pair for pair in changes if pair[1].change_ratio is not None and pair[1].change_ratio < 0),
            key=lambda pair: (pair[1].change_ratio, pair[0]),
        )
    )
    from_zero = tuple(
        change
        for _, change in sorted(
            (pair for pair in changes if pair[1].change_ratio is None),
            key=lambda pair: (-pair[1].change, pair[0]),
        )
    )
    flagged = sorted(
        (
            (key, change)
            for key, change in changes
            if change.anomaly and change.change_ratio is not None
        ),
        key=lambda pair: (-abs(pair[1].change_ratio), pair[0]),
    )
    anomalies = from_zero + tuple(change for _, change in flagged)

    new_products = priced(after, after.keys() - before.keys() - left_out)
    discontinued = priced(before, before.keys() - after.keys() - left_out)
    summary = ReportSummary(
        unchanged,
        len(increases),
        len(decreases),
        len(from_zero),
        len(new_products),
        len(discontinued),
        len(currency_changed),
        len(ambiguous),
        len(anomalies),
        _median([item.change_ratio for item in increases + decreases]),
    )
    return PriceReport(
        threshold,
        increases,
        decreases,
        from_zero,
        new_products,
        discontinued,
        tuple(item for _, item in currency_changed),
        ambiguous,
        unchanged,
        anomalies,
        summary,
    )
