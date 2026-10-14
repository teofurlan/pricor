"""Pure parsers for untrusted cell text.

Every parser either returns an exact `Decimal` / string or raises `CellError`
with a human-readable reason. Nothing here uses float or evaluates input.
"""

import re
from decimal import Decimal

MAX_CELL_LENGTH = 64

_PLAIN_NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]+)?", re.ASCII)
_SIGNED_PLAIN_NUMBER = re.compile(r"-?[0-9]+(?:[.,][0-9]+)?", re.ASCII)
_NUMERIC_CHARS = frozenset("0123456789")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"))


class CellError(ValueError):
    """A cell value cannot be interpreted. The message is the rejection reason."""


def _clean(text: str) -> str:
    return text.replace(" ", " ").strip()


def _percent(raw: str) -> Decimal:
    return Decimal(raw.replace(",", "."))


def parse_number(text: str, decimal_sep: str, thousands_sep: str) -> Decimal:
    """Parse a formatted number such as `$ 12.100,00` into an exact Decimal.

    Currency symbols and letters around the number are ignored; the number
    itself must follow the given separators strictly (no guessing).
    """
    value = _clean(text)
    if not value:
        raise CellError("empty value, expected a number")
    if len(value) > MAX_CELL_LENGTH:
        raise CellError("value too long to be a number")

    start = 0
    while start < len(value) and value[start] not in _NUMERIC_CHARS | set("+-.,"):
        start += 1
    end = len(value)
    while end > start and value[end - 1] not in _NUMERIC_CHARS | set(".,"):
        end -= 1
    core = value[start:end].strip()

    sign = ""
    if core[:1] in ("+", "-"):
        sign, core = core[0], core[1:]
    if sign == "+":
        sign = ""

    decimal_pattern = re.escape(decimal_sep)
    if thousands_sep:
        thousands_pattern = re.escape(thousands_sep)
        integer_pattern = rf"(?:[0-9]{{1,3}}(?:{thousands_pattern}[0-9]{{3}})+|[0-9]+)"
    else:
        integer_pattern = r"[0-9]+"
    match = re.fullmatch(
        rf"(?P<integer>{integer_pattern})?(?:{decimal_pattern}(?P<fraction>[0-9]+))?",
        core,
        re.ASCII,
    )
    if not core or match is None or (match["integer"] is None and match["fraction"] is None):
        raise CellError(f"not a number: {text.strip()!r}")

    digits = match["integer"] or "0"
    if thousands_sep:
        digits = digits.replace(thousands_sep, "")
    literal = f"{sign}{digits}"
    if match["fraction"] is not None:
        literal += f".{match['fraction']}"
    return Decimal(literal)


def parse_discounts(text: str) -> tuple[Decimal, ...]:
    """Parse chained discounts such as `10+5` or `10% + 5%`. Empty means none."""
    value = re.sub(r"[%\s]", "", _clean(text))
    if not value:
        return ()
    percents = []
    for part in value.split("+"):
        if not _PLAIN_NUMBER.fullmatch(part):
            raise CellError(f"unreadable discount: {text.strip()!r}")
        percent = _percent(part)
        if percent > 100:
            raise CellError(f"discount out of range (0-100): {text.strip()!r}")
        percents.append(percent)
    return tuple(percents)


def parse_rate(text: str) -> Decimal:
    """Parse a VAT rate such as `21%`, `10,5%` or `21`."""
    value = _clean(text)
    if value.endswith("%"):
        value = value[:-1].strip()
    if not value:
        raise CellError("empty value, expected a VAT rate")
    if not _PLAIN_NUMBER.fullmatch(value):
        raise CellError(f"unreadable VAT rate: {text.strip()!r}")
    rate = _percent(value)
    if rate > 100:
        raise CellError(f"VAT rate out of range (0-100): {text.strip()!r}")
    return rate


def parse_units(text: str) -> Decimal:
    """Parse units per pack. Must be a positive number."""
    value = _clean(text)
    if not value:
        raise CellError("units per pack is empty")
    if not _SIGNED_PLAIN_NUMBER.fullmatch(value):
        raise CellError(f"units per pack is not a number: {text.strip()!r}")
    units = _percent(value)
    if units == 0:
        raise CellError("units per pack is zero")
    if units < 0:
        raise CellError(f"units per pack must be positive: {text.strip()!r}")
    return units


def normalize_text(text: str) -> str:
    """Trim, collapse inner whitespace, unify non-breaking spaces, drop zero-width chars."""
    return " ".join(text.translate(_ZERO_WIDTH).split())


def lookup_key(text: str) -> str:
    """Key under which `map_values` compares a cell with a table key (trim, collapse, casefold)."""
    return normalize_text(text).casefold()
