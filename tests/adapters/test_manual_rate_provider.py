from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pricor.adapters.manual_rate_provider import ManualRateProvider
from pricor.ports.fx_rates import FxInvalidRateError

NOW = datetime(2026, 10, 14, 15, 30, tzinfo=UTC)


def test_a_typed_rate_becomes_a_manual_snapshot_dated_now():
    snapshot = ManualRateProvider("1420,50", clock=lambda: NOW).snapshot("USD", "ARS", "oficial", "compra")

    assert snapshot.rate == Decimal("1420.50")
    assert (snapshot.source, snapshot.rate_type, snapshot.side) == ("manual", "manual", "compra")
    assert (snapshot.from_currency, snapshot.to_currency) == ("USD", "ARS")
    assert snapshot.quoted_at == NOW
    assert snapshot.stale is False


@pytest.mark.parametrize("text", ["1500", "1500.5", " 1.500,25 ", "0.0001"])
def test_accepts_plain_numbers_with_either_decimal_mark(text):
    assert ManualRateProvider(text, clock=lambda: NOW).snapshot("USD", "ARS", "blue", "venta").rate > 0


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "NaN", "Infinity", "1e400", "12 34"])
def test_rejects_rates_that_are_not_positive_finite_numbers(text):
    with pytest.raises(FxInvalidRateError):
        ManualRateProvider(text, clock=lambda: NOW)
