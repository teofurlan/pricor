"""Deterministic profile of one spreadsheet sheet.

The profiler answers, without any model: where the header is, which rows are
data / empty / totals / section titles / preamble, and what each column looks
like (apparent type, null and distinct ratios, currency markers, number
format, representative and atypical samples). Nothing is dropped silently:
every row other than the header gets exactly one class.

Row indexes are 0-based positions in the sheet; the 1-based file row number is
`index + 1`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .cells import (
    CellKind,
    CellShape,
    NumberFormat,
    classify_cell,
    detect_number_format,
    display,
    find_currency_markers,
    is_blank,
)
from .parsing import CellError, normalize_text, parse_number
from .plan import column_header

HEADER_SEARCH_ROWS = 30
_MAX_REPRESENTATIVE = 5
_MAX_OFF_TYPE = 3
_TYPE_THRESHOLD = 0.8
_MIN_HEADER_CELL_SHARE = 0.8  # share of non-blank cells that must be non-numeric text
_HEADER_WIDTH_SHARE = 0.7  # a header must be at least this wide relative to the widest candidate
_TOTAL_LABEL = re.compile(r"(?:sub\s*-?\s*)?total(?:es)?\b", re.IGNORECASE)

Row = Sequence[Any]


class RowClass(StrEnum):
    DATA = "data"
    EMPTY = "empty"
    TOTAL = "total"
    SECTION = "section"
    PREAMBLE = "preamble"  # non-empty rows above the header: titles, banners, contact lines


class ColumnType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENT = "percent"
    MONEY = "money"
    BARCODE = "barcode"
    CODE = "code"
    DATE = "date"
    EMPTY = "empty"


@dataclass(frozen=True)
class RowClassification:
    index: int
    kind: RowClass


@dataclass(frozen=True)
class Sample:
    kind: str  # "min", "max", "longest" or "off_type"
    value: str
    row_index: int


@dataclass(frozen=True)
class ColumnProfile:
    index: int
    raw_header: str
    header: str  # normalized: trimmed, whitespace collapsed, case-folded
    apparent_type: ColumnType
    null_ratio: float
    distinct_ratio: float
    currencies: tuple[str, ...]  # markers seen in cell values
    header_currencies: tuple[str, ...]  # markers seen in the header text
    number_format: NumberFormat | None
    samples: tuple[str, ...]
    atypical: tuple[Sample, ...]

    @property
    def plan_header(self) -> str:
        """The header plans use for this column (`column_N` when it has none)."""
        return column_header(self.index, self.raw_header)


@dataclass(frozen=True)
class SheetProfile:
    header_row: int | None
    header_confidence: float
    header_ambiguous: bool
    duplicated_headers: tuple[str, ...]
    row_classes: tuple[RowClassification, ...]
    columns: tuple[ColumnProfile, ...]

    @property
    def class_counts(self) -> dict[RowClass, int]:
        counts = dict.fromkeys(RowClass, 0)
        for item in self.row_classes:
            counts[item.kind] += 1
        return counts

    def indexes_of(self, kind: RowClass) -> list[int]:
        return [item.index for item in self.row_classes if item.kind is kind]


# -- header detection -----------------------------------------------------------


def _non_blank(row: Row) -> list[Any]:
    return [cell for cell in row if not is_blank(cell)]


def _header_like(row: Row) -> bool:
    """True when the non-blank cells read as labels rather than values."""
    cells = _non_blank(row)
    if not cells:
        return False
    labels = sum(
        1
        for cell in cells
        if isinstance(cell, str)
        and classify_cell(cell).kind in (CellKind.TEXT, CellKind.CODE)
    )
    return labels / len(cells) >= _MIN_HEADER_CELL_SHARE


def _normalize_header(raw: str) -> str:
    return normalize_text(raw).casefold()


def _detect_header(rows: Sequence[Row]) -> tuple[int | None, float, bool]:
    """Return (header index, confidence 0..1, ambiguous)."""
    widest_sheet = max((len(_non_blank(row)) for row in rows), default=0)
    min_width = min(2, widest_sheet)
    window = range(min(HEADER_SEARCH_ROWS, len(rows)))
    candidates = [
        i for i in window if len(_non_blank(rows[i])) >= max(min_width, 1) and _header_like(rows[i])
    ]
    if not candidates:
        return None, 0.0, True
    widest = max(len(_non_blank(rows[i])) for i in candidates)
    best = next(i for i in candidates if len(_non_blank(rows[i])) >= _HEADER_WIDTH_SHARE * widest)
    width = len(_non_blank(rows[best]))

    following = [row for row in rows[best + 1 :] if len(_non_blank(row)) >= 2][:5]
    width_support = (
        sum(1 for row in following if len(_non_blank(row)) >= width / 2) / len(following)
        if following
        else 0.0
    )
    numeric_support = float(
        any(
            classify_cell(cell).kind in (CellKind.INTEGER, CellKind.DECIMAL, CellKind.PERCENT)
            for row in following
            for cell in _non_blank(row)
        )
    )
    labels = [_normalize_header(display(cell)) for cell in _non_blank(rows[best])]
    uniqueness = len(set(labels)) / len(labels)
    window_width = max(len(_non_blank(rows[i])) for i in window)
    confidence = (
        0.35 * width_support
        + 0.25 * numeric_support
        + 0.20 * uniqueness
        + 0.20 * min(1.0, width / window_width)
    )

    stacked = bool(following) and (
        _header_like(following[0]) and len(_non_blank(following[0])) >= _HEADER_WIDTH_SHARE * width
    )
    ambiguous = stacked or confidence < 0.5
    return best, round(confidence, 3), ambiguous


# -- row classification ---------------------------------------------------------


def _classify_row(row: Row, index: int, header_row: int | None, table_width: int) -> RowClass:
    cells = _non_blank(row)
    if not cells:
        return RowClass.EMPTY
    if header_row is not None and index < header_row:
        return RowClass.PREAMBLE
    first = cells[0]
    if isinstance(first, str) and _TOTAL_LABEL.match(normalize_text(first)):
        return RowClass.TOTAL
    if (
        len(cells) == 1
        and table_width > 1
        and isinstance(first, str)
        and classify_cell(first).kind is CellKind.TEXT  # a lone code-like cell is a sparse data row
    ):
        return RowClass.SECTION
    return RowClass.DATA


# -- column profiling -----------------------------------------------------------


def _cell(row: Row, index: int) -> Any:
    return row[index] if index < len(row) else None


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def _decide_type(shapes: list[CellShape]) -> ColumnType:
    total = len(shapes)
    if total == 0:
        return ColumnType.EMPTY
    barcode = sum(shape.barcode_like for shape in shapes)
    percent = sum(shape.kind is CellKind.PERCENT for shape in shapes)
    numeric_kinds = (CellKind.INTEGER, CellKind.DECIMAL)
    numeric = sum(shape.kind in numeric_kinds for shape in shapes)
    marked = sum(bool(shape.markers) for shape in shapes)
    dates = sum(shape.kind is CellKind.DATE for shape in shapes)
    codes = sum(shape.kind is CellKind.CODE for shape in shapes)
    if _share(barcode, total) >= _TYPE_THRESHOLD:
        return ColumnType.BARCODE
    if _share(percent, total) >= _TYPE_THRESHOLD:
        return ColumnType.PERCENT
    if _share(numeric, total) >= _TYPE_THRESHOLD:
        if _share(marked, total) >= 0.5:
            return ColumnType.MONEY
        if any(shape.kind is CellKind.DECIMAL for shape in shapes):
            return ColumnType.DECIMAL
        return ColumnType.INTEGER
    if _share(dates, total) >= _TYPE_THRESHOLD:
        return ColumnType.DATE
    if _share(codes, total) >= _TYPE_THRESHOLD:
        return ColumnType.CODE
    return ColumnType.TEXT


def _fits(column_type: ColumnType, shape: CellShape) -> bool:
    match column_type:
        case ColumnType.BARCODE:
            return shape.barcode_like
        case ColumnType.PERCENT:
            return shape.kind is CellKind.PERCENT
        case ColumnType.INTEGER:
            return shape.kind is CellKind.INTEGER
        case ColumnType.DECIMAL | ColumnType.MONEY:
            return shape.kind in (CellKind.INTEGER, CellKind.DECIMAL)
        case ColumnType.DATE:
            return shape.kind is CellKind.DATE
        case ColumnType.CODE:
            return shape.kind is CellKind.CODE
        case _:
            return True


_NUMERIC_TYPES = frozenset(
    {ColumnType.INTEGER, ColumnType.DECIMAL, ColumnType.PERCENT, ColumnType.MONEY}
)


def _numeric_value(value: Any, fmt: NumberFormat) -> Decimal | None:
    """Numeric value of a cell under the detected format, or None when unreadable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | Decimal):
        return Decimal(value) if value == value else None
    if not isinstance(value, str):
        return None
    try:
        # Plain digit strings need no separators; ambiguity was excluded by the caller.
        return parse_number(value, fmt.decimal_sep or ".", fmt.thousands_sep or "")
    except CellError:
        return None


def _representative(values: list[str]) -> tuple[str, ...]:
    distinct = list(dict.fromkeys(values))
    if len(distinct) <= _MAX_REPRESENTATIVE:
        return tuple(distinct)
    last = len(distinct) - 1
    picks = sorted({round(i * last / (_MAX_REPRESENTATIVE - 1)) for i in range(_MAX_REPRESENTATIVE)})
    return tuple(distinct[i] for i in picks)


def _atypical(
    entries: list[tuple[int, Any, CellShape]], column_type: ColumnType, fmt: NumberFormat | None
) -> tuple[Sample, ...]:
    samples: list[Sample] = []
    if column_type in _NUMERIC_TYPES and fmt is not None and not fmt.ambiguous:
        numbers = [
            (number, row_index, value)
            for row_index, value, shape in entries
            if _fits(column_type, shape) or shape.kind is CellKind.PERCENT
            if (number := _numeric_value(value, fmt)) is not None
        ]
        if numbers:
            low = min(numbers, key=lambda item: item[0])
            high = max(numbers, key=lambda item: item[0])
            samples.append(Sample("min", display(low[2]), low[1]))
            samples.append(Sample("max", display(high[2]), high[1]))
    if entries:
        row_index, value, _ = max(entries, key=lambda item: len(display(item[1])))
        samples.append(Sample("longest", display(value), row_index))
    off_type = [
        Sample("off_type", display(value), row_index)
        for row_index, value, shape in entries
        if not _fits(column_type, shape)
    ]
    samples.extend(off_type[:_MAX_OFF_TYPE])
    return tuple(samples)


def _profile_column(index: int, raw_header: str, data: list[tuple[int, Row]]) -> ColumnProfile:
    entries = [
        (row_index, value, classify_cell(value))
        for row_index, row in data
        if not is_blank(value := _cell(row, index))
    ]
    shapes = [shape for _, _, shape in entries]
    column_type = _decide_type(shapes)
    texts = [display(value) for _, value, _ in entries]

    fmt: NumberFormat | None = None
    if column_type in _NUMERIC_TYPES:
        bodies = [shape.body for shape in shapes if shape.body is not None]
        fmt = detect_number_format(bodies, sum(shape.native for shape in shapes))

    markers: dict[str, None] = {}
    for shape in shapes:
        markers.update(dict.fromkeys(shape.markers))
    normalized = [normalize_text(text) for text in texts]
    return ColumnProfile(
        index=index,
        raw_header=raw_header,
        header=_normalize_header(raw_header),
        apparent_type=column_type,
        null_ratio=1 - _share(len(entries), len(data)) if data else 0.0,
        distinct_ratio=_share(len(set(normalized)), len(normalized)),
        currencies=tuple(markers),
        header_currencies=find_currency_markers(raw_header),
        number_format=fmt,
        samples=_representative(texts),
        atypical=_atypical(entries, column_type, fmt),
    )


# -- entry points ---------------------------------------------------------------


def profile_sheet(rows: Sequence[Row]) -> SheetProfile:
    """Profile the rows of one sheet."""
    header_row, confidence, ambiguous = _detect_header(rows)
    if header_row is not None:
        table_width = len(_non_blank(rows[header_row]))
    else:
        table_width = max((len(_non_blank(row)) for row in rows), default=0)

    row_classes = tuple(
        RowClassification(index, _classify_row(row, index, header_row, table_width))
        for index, row in enumerate(rows)
        if index != header_row
    )
    data = [(item.index, rows[item.index]) for item in row_classes if item.kind is RowClass.DATA]

    header_cells = list(rows[header_row]) if header_row is not None else []
    width = max([len(header_cells)] + [len(row) for _, row in data], default=0)
    raw_headers = [
        display(header_cells[i]) if i < len(header_cells) and header_cells[i] is not None else ""
        for i in range(width)
    ]
    normalized = [_normalize_header(raw) for raw in raw_headers if raw.strip()]
    duplicated = tuple(name for name in dict.fromkeys(normalized) if normalized.count(name) > 1)
    columns = tuple(_profile_column(i, raw_headers[i], data) for i in range(width))
    return SheetProfile(header_row, confidence, ambiguous, duplicated, row_classes, columns)


def engine_input(
    rows: Sequence[Row], profile: SheetProfile
) -> tuple[list[str], list[tuple[int, Row]]]:
    """Return `(headers, [(file_row_number, row), ...])` for the plan engine.

    Only `data` rows are returned; the others stay visible in `profile.row_classes`.
    Row numbers are 1-based file rows, so rejections point at the right line.
    """
    if profile.header_row is None:
        raise ValueError("no header row was detected; choose one before running a plan")
    headers = [column.plan_header for column in profile.columns]
    data = [(index + 1, rows[index]) for index in profile.indexes_of(RowClass.DATA)]
    return headers, data
