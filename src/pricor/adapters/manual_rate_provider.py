"""A rate the user typed in, offered through the same port as the live source."""

from collections.abc import Callable
from datetime import UTC, datetime

from pricor.domain.fx import FxSnapshot, manual_snapshot


class ManualRateProvider:
    """Raises `FxInvalidRateError` at construction if the text is not a positive number."""

    def __init__(self, rate_text: str, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._text = rate_text
        self._clock = clock
        manual_snapshot(rate_text, "USD", "ARS", "venta", clock())  # validate now, not later

    def snapshot(
        self, from_currency: str, to_currency: str, rate_type: str, side: str
    ) -> FxSnapshot:
        return manual_snapshot(self._text, from_currency, to_currency, side, self._clock())
