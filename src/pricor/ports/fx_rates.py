"""Ports for exchange rates: where a run's `FxSnapshot` comes from.

The plan stores only a rate type; a provider turns that into today's rate for one run. A
provider never guesses: it returns a snapshot or raises one of the typed errors below.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from pricor.domain.fx import FxInvalidRateError, FxSnapshot

__all__ = [
    "CachedQuote",
    "FxError",
    "FxInvalidRateError",
    "FxInvalidReplyError",
    "FxQuoteCache",
    "FxRateProvider",
    "FxUnavailableError",
    "FxUnsupportedError",
]


class FxError(Exception):
    """Base class for exchange-rate failures. Messages are safe to show to the user."""


class FxUnavailableError(FxError):
    """The source cannot be reached and there is no cached quote to fall back on."""


class FxInvalidReplyError(FxError):
    """The source answered with something that is not a usable quote."""


class FxUnsupportedError(FxError):
    """The source does not publish this currency pair, rate type or side."""


@dataclass(frozen=True)
class CachedQuote:
    """The last successful quote of one rate type, both sides, as the source published it."""

    rate_type: str
    compra: Decimal
    venta: Decimal
    quoted_at: datetime


class FxQuoteCache(Protocol):
    def save(self, quote: CachedQuote) -> None:
        """Remember `quote` as the latest for its rate type."""
        ...

    def last(self, rate_type: str) -> CachedQuote | None: ...


class FxRateProvider(Protocol):
    def snapshot(
        self, from_currency: str, to_currency: str, rate_type: str, side: str
    ) -> FxSnapshot:
        """The rate for one run, or raise an `FxError`."""
        ...
