"""Shape analysis of untrusted cell values, used by the profiler.

Nothing here interprets a value beyond describing what it looks like: whether
it reads as a number, a percent, a date or a code, which currency markers it
carries, and which decimal/thousands separators it implies. No float, no eval.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .parsing import normalize_text

BARCODE_LENGTHS = frozenset({8, 12, 13, 14})
_MAX_CODE_LENGTH = 20

_CURRENCY = re.compile(
    r"U\$S|US\$|U\$D|AR\$|\$|€|(?<![A-Za-z])(?:USD|ARS|EUR)(?![A-Za-z])",
    re.IGNORECASE,
)
_NUMBER_BODY = re.compile(r"[+-]?[0-9]+(?:[.,][0-9]+)*", re.ASCII)
_DATE = re.compile(
    r"[0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?",
    re.ASCII,
)
_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/\-]*", re.ASCII)


class CellKind(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENT = "percent"
    DATE = "date"
    CODE = "code"
    TEXT = "text"


@dataclass(frozen=True)
class CellShape:
    kind: CellKind
    barcode_like: bool = False
    markers: tuple[str, ...] = ()
    # Numeric text without markers/percent sign, for textual numbers only.
    body: str | None = None
    native: bool = False


def display(value: Any) -> str:
    """Stable text form of a cell for samples and evidence."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not normalize_text(value))


def find_currency_markers(text: str) -> tuple[str, ...]:
    """Distinct currency markers in order of appearance, upper-cased."""
    seen: dict[str, None] = {}
    for match in _CURRENCY.finditer(text):
        seen.setdefault(match.group().upper())
    return tuple(seen)


def _native_shape(value: Any) -> CellShape:
    if isinstance(value, datetime | date):
        return CellShape(CellKind.DATE, native=True)
    if isinstance(value, bool):
        return CellShape(CellKind.TEXT, native=True)
    if isinstance(value, int | Decimal):
        if isinstance(value, Decimal) and not value.is_finite():
            return CellShape(CellKind.TEXT, native=True)
        integral = isinstance(value, int) or value == value.to_integral_value()
        digits = str(int(abs(value))) if integral else ""
        barcode = integral and value > 0 and len(digits) in BARCODE_LENGTHS
        whole = isinstance(value, int) or value.as_tuple().exponent >= 0
        kind = CellKind.INTEGER if whole else CellKind.DECIMAL
        return CellShape(kind, barcode_like=barcode, native=True)
    return CellShape(CellKind.TEXT, native=True)


def _plausible_number(body: str) -> bool:
    """Reject dotted/comma references such as `1.5.12` that are not valid digit grouping."""
    separators = sum(char in ".," for char in body)
    return separators < 2 or _vote(body) is not None


def classify_cell(value: Any) -> CellShape:
    """Describe one non-blank cell."""
    if not isinstance(value, str):
        return _native_shape(value)
    text = normalize_text(value)
    if _DATE.fullmatch(text):
        return CellShape(CellKind.DATE)
    markers = find_currency_markers(text)
    is_percent = text.endswith("%")
    body = _CURRENCY.sub("", text).replace("%", "").replace(" ", "")
    if _NUMBER_BODY.fullmatch(body) and _plausible_number(body):
        digits_only = body.isdigit()
        barcode = digits_only and len(body) in BARCODE_LENGTHS and not markers and not is_percent
        if is_percent:
            kind = CellKind.PERCENT
        elif digits_only and not markers and len(body) > 1 and body.startswith("0"):
            kind = CellKind.CODE  # leading zeros are meaningful: not a quantity
        elif digits_only:
            kind = CellKind.INTEGER
        else:
            kind = CellKind.DECIMAL
        return CellShape(kind, barcode_like=barcode, markers=markers, body=body)
    if (
        _CODE.fullmatch(text)
        and len(text) <= _MAX_CODE_LENGTH
        and any(char.isdigit() for char in text)
    ):
        return CellShape(CellKind.CODE)
    return CellShape(CellKind.TEXT, markers=markers)


# -- number format -------------------------------------------------------------


@dataclass(frozen=True)
class NumberFormat:
    decimal_sep: str | None
    thousands_sep: str | None
    evidence: str
    ambiguous: bool


def _other(separator: str) -> str:
    return "." if separator == "," else ","


def _vote(body: str) -> tuple[str, str] | None:
    """Classify one numeric text: ('decimal', sep), ('ambiguous', sep) or None (no info)."""
    unsigned = body.lstrip("+-")
    separators = [char for char in unsigned if char in ".,"]
    if not separators:
        return None
    kinds = set(separators)
    if len(kinds) == 2:
        last = separators[-1]
        thousands = _other(last)
        head, _, tail = unsigned.rpartition(last)
        parts = head.split(thousands)
        valid = (
            last not in head
            and 1 <= len(parts[0]) <= 3
            and all(len(part) == 3 for part in parts[1:])
            and tail.isdigit()
        )
        return ("decimal", last) if valid else None
    separator = separators[0]
    parts = unsigned.split(separator)
    if len(separators) > 1:
        valid = 1 <= len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:])
        # Repeated single separator can only be grouping, so the other one is the decimal.
        return ("decimal", _other(separator)) if valid else None
    integer, fraction = parts
    if len(fraction) == 3 and 1 <= len(integer) <= 3 and integer != "0":
        return ("ambiguous", separator)
    return ("decimal", separator)


def detect_number_format(bodies: list[str], native_count: int) -> NumberFormat:
    """Infer the separators of a numeric column from its textual values."""
    if not bodies:
        evidence = "native numeric cells carry no separators" if native_count else "no values"
        return NumberFormat(None, None, evidence, False)
    decimal_votes: dict[str, list[str]] = {",": [], ".": []}
    ambiguous_examples: list[str] = []
    for body in bodies:
        vote = _vote(body)
        if vote is None:
            continue
        if vote[0] == "decimal":
            decimal_votes[vote[1]].append(body)
        else:
            ambiguous_examples.append(body)
    proven = {sep: examples for sep, examples in decimal_votes.items() if examples}
    if len(proven) == 2:
        comma, dot = proven[","][0], proven["."][0]
        return NumberFormat(
            None,
            None,
            f"conflicting evidence: ',' is decimal in {comma!r} but '.' is decimal in {dot!r}",
            True,
        )
    if len(proven) == 1:
        ((separator, examples),) = proven.items()
        return NumberFormat(
            separator,
            _other(separator),
            f"{separator!r} is the decimal separator: {len(examples)} value(s) prove it, "
            f"e.g. {examples[0]!r}",
            False,
        )
    if ambiguous_examples:
        return NumberFormat(
            None,
            None,
            f"{len(ambiguous_examples)} value(s) such as {ambiguous_examples[0]!r} read as "
            "either thousands groups or decimals, and nothing else settles it",
            True,
        )
    return NumberFormat(None, None, "no separators in any value", False)
