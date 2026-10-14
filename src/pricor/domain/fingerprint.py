"""Sheet fingerprints and the comparison that tells a supplier's new file from the saved one.

A fingerprint is what a plan was approved against: for every column its
position, its normalized header and its apparent type. Comparing it with the
profile of a new file sorts every column into exactly one class:

* unchanged: same header at the same position, compatible type;
* moved: same header and compatible type at another position;
* retyped: same header but the values no longer look like the same kind of data;
* new: a column of the new file that has no counterpart;
* missing: a saved column that has no counterpart (flagged when the plan uses it).

Matching is deterministic. Columns are paired by normalized header: the k-th saved
column with a header is paired with the k-th column of the new file that has it, so
duplicated headers keep their relative order. A column without a header can only be
paired with a header-less column at the same position.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from .plan import ImportPlan
from .plan_roles import column_roles
from .profile import ColumnProfile, ColumnType, SheetProfile


@dataclass(frozen=True)
class ColumnFingerprint:
    index: int
    header: str  # normalized: trimmed, whitespace collapsed, case-folded
    apparent_type: str  # `ColumnType` value


@dataclass(frozen=True)
class SheetFingerprint:
    sheet_name: str
    header_row: int | None
    columns: tuple[ColumnFingerprint, ...]


def fingerprint_of(profile: SheetProfile, sheet_name: str) -> SheetFingerprint:
    return SheetFingerprint(
        sheet_name,
        profile.header_row,
        tuple(
            ColumnFingerprint(column.index, column.header, column.apparent_type.value)
            for column in profile.columns
        ),
    )


# Types that can stand in for each other when the same header shows up again: a price column
# is an integer in a list of round prices and a decimal in the next one. Everything else is a
# real change of kind (a percent is not a price; an empty column says nothing).
_FAMILIES = (
    frozenset({ColumnType.INTEGER, ColumnType.DECIMAL, ColumnType.MONEY}),
    frozenset({ColumnType.TEXT, ColumnType.CODE}),
)


def types_compatible(saved: str, current: str) -> bool:
    if saved == current:
        return True
    return any(
        ColumnType(saved) in family and ColumnType(current) in family for family in _FAMILIES
    )


@dataclass(frozen=True)
class ColumnChange:
    """A pairing (or the lack of one) between a saved column and a column of the new file.

    `header` is the normalized header. `saved_*` is empty for a new column and `new_*` for a
    missing one. `used_by_plan` only means something for missing columns.
    """

    header: str
    saved_index: int | None
    new_index: int | None
    saved_type: str | None
    new_type: str | None
    used_by_plan: bool = False


@dataclass(frozen=True)
class FingerprintComparison:
    unchanged: tuple[ColumnChange, ...]
    moved: tuple[ColumnChange, ...]
    retyped: tuple[ColumnChange, ...]
    new: tuple[ColumnChange, ...]
    missing: tuple[ColumnChange, ...]
    sheet_change: tuple[str, str] | None  # (saved name, new name)
    header_row_change: tuple[int | None, int | None] | None  # (saved index, new index)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.moved
            or self.retyped
            or self.new
            or self.missing
            or self.sheet_change
            or self.header_row_change
        )


def _pair(saved: Sequence[ColumnFingerprint], columns: Sequence[ColumnProfile]):
    pairs: list[tuple[ColumnFingerprint, ColumnProfile]] = []
    taken: set[int] = set()
    unmatched: list[ColumnFingerprint] = []
    by_index = {column.index: column for column in columns}
    for header in dict.fromkeys(fingerprint.header for fingerprint in saved):
        old = [fingerprint for fingerprint in saved if fingerprint.header == header]
        if header:
            new = [column for column in columns if column.header == header]
            candidates = dict(zip((f.index for f in old), new))  # k-th occurrence with k-th
        else:
            candidates = {
                f.index: by_index[f.index]
                for f in old
                if f.index in by_index and not by_index[f.index].header
            }
        for fingerprint in old:
            column = candidates.get(fingerprint.index)
            if column is None:
                unmatched.append(fingerprint)
            else:
                pairs.append((fingerprint, column))
                taken.add(column.index)
    free = [column for column in columns if column.index not in taken]
    return pairs, free, sorted(unmatched, key=lambda fingerprint: fingerprint.index)


def compare_fingerprint(
    saved: SheetFingerprint,
    profile: SheetProfile,
    sheet_name: str | None = None,
    plan: ImportPlan | None = None,
) -> FingerprintComparison:
    """Sort the columns of `profile` against `saved`.

    `sheet_name` is compared only when given; `plan` is only used to flag which missing
    columns it reads.
    """
    used = set(column_roles(plan)) if plan is not None else set()
    pairs, free, missing = _pair(saved.columns, profile.columns)

    unchanged: list[ColumnChange] = []
    moved: list[ColumnChange] = []
    retyped: list[ColumnChange] = []
    for fingerprint, column in sorted(pairs, key=lambda pair: pair[0].index):
        change = ColumnChange(
            column.header,
            fingerprint.index,
            column.index,
            fingerprint.apparent_type,
            column.apparent_type.value,
        )
        if not types_compatible(fingerprint.apparent_type, column.apparent_type.value):
            retyped.append(change)
        elif fingerprint.index != column.index:
            moved.append(change)
        else:
            unchanged.append(change)

    return FingerprintComparison(
        tuple(unchanged),
        tuple(moved),
        tuple(retyped),
        tuple(
            ColumnChange(column.header, None, column.index, None, column.apparent_type.value)
            for column in free
        ),
        tuple(
            ColumnChange(
                fingerprint.header,
                fingerprint.index,
                None,
                fingerprint.apparent_type,
                None,
                used_by_plan=fingerprint.index in used,
            )
            for fingerprint in missing
        ),
        (saved.sheet_name, sheet_name)
        if sheet_name is not None and sheet_name != saved.sheet_name
        else None,
        (saved.header_row, profile.header_row) if saved.header_row != profile.header_row else None,
    )
