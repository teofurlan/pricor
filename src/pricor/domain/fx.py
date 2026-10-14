"""Foreign-exchange vocabulary and the per-run rate snapshot.

A plan only names *which* rate to use (`rate_type`, `side`); the rate itself belongs to the run.
An `FxSnapshot` is that rate, frozen with where and when it came from, so a conversion can always
be explained and repeated.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

MANUAL = "manual"
# Rate types published by DolarAPI, plus a rate the user types in.
MARKET_RATE_TYPES = (
    "oficial",
    "blue",
    "bolsa",
    "contadoconliqui",
    "mayorista",
    "cripto",
    "tarjeta",
)
RATE_TYPES = frozenset({*MARKET_RATE_TYPES, MANUAL})
SIDES = ("compra", "venta")
DEFAULT_SIDE = "venta"
TARGET_CURRENCY = "ARS"


class FxSnapshotRequiredError(Exception):
    """The plan converts currency but the run has no rate snapshot. The engine never guesses."""


class FxSnapshotMismatchError(Exception):
    """The snapshot is for another rate type, side or currency pair than the plan asks for."""


@dataclass(frozen=True)
class FxSnapshot:
    """One exchange rate (`1 from_currency = rate to_currency`) used by one run.

    `quoted_at` is when the source published the quote, so a `stale` cached quote keeps its
    own date. A `manual` snapshot satisfies a plan whatever its rate type is.
    """

    rate: Decimal
    rate_type: str
    side: str
    source: str  # "dolarapi" or "manual"
    quoted_at: datetime
    from_currency: str = "USD"
    to_currency: str = TARGET_CURRENCY
    stale: bool = False

    @property
    def label(self) -> str:
        """How the rate is named in records and files."""
        return MANUAL if self.source == MANUAL else f"{self.source}:{self.rate_type}:{self.side}"

    @property
    def date(self) -> str:
        return self.quoted_at.date().isoformat()


class FxInvalidRateError(ValueError):
    """A typed exchange rate is not a positive number."""


_RATE_TEXT = re.compile(r"[0-9]+(?:\.[0-9]+)?", re.ASCII)


def parse_rate_text(text: str) -> Decimal:
    """A user-typed rate: digits with `.` or `,` as the decimal mark (`1.500,25` is allowed).

    With a comma present, dots are thousands separators; otherwise the dot is the decimal mark.
    """
    value = text.strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    if not _RATE_TEXT.fullmatch(value) or Decimal(value) <= 0:
        raise FxInvalidRateError(f"{text!r} is not a positive number such as 1500 or 1500,50")
    return Decimal(value)


def manual_snapshot(
    text: str, from_currency: str, to_currency: str, side: str, quoted_at: datetime
) -> FxSnapshot:
    """The snapshot for a rate the user typed in; it satisfies a plan of any rate type."""
    return FxSnapshot(
        parse_rate_text(text), MANUAL, side, MANUAL, quoted_at, from_currency, to_currency
    )
