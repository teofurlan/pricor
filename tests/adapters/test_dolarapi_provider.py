import json
import urllib.error
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pricor.adapters.dolarapi_provider import DOLARAPI_URL, DolarApiProvider
from pricor.ports.fx_rates import (
    CachedQuote,
    FxInvalidReplyError,
    FxUnavailableError,
    FxUnsupportedError,
)

REPLY = (
    b'[{"moneda":"USD","casa":"oficial","nombre":"Oficial","compra":1485,"venta":1535,'
    b'"fechaActualizacion":"2026-10-14T10:00:00.000Z"},'
    b'{"moneda":"USD","casa":"blue","nombre":"Blue","compra":1530.5,"venta":1550.25,'
    b'"fechaActualizacion":"2026-10-14T12:56:00.000Z"}]'
)


class FakeTransport:
    def __init__(self, reply=REPLY, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        return self.reply


class MemoryCache:
    def __init__(self):
        self.items = {}

    def save(self, quote):
        self.items[quote.rate_type] = quote

    def last(self, rate_type):
        return self.items.get(rate_type)


def provider(transport=None, cache=None, **kwargs):
    return DolarApiProvider(transport or FakeTransport(), cache or MemoryCache(), **kwargs)


def ask(prov, rate_type="oficial", side="venta", source="USD", target="ARS"):
    return prov.snapshot(source, target, rate_type, side)


def test_asks_the_public_endpoint_once_with_a_timeout():
    transport = FakeTransport()

    ask(provider(transport, timeout=7))

    assert transport.calls == [(DOLARAPI_URL, 7)]
    assert DOLARAPI_URL == "https://dolarapi.com/v1/dolares"


def test_returns_the_requested_rate_type_and_side_as_an_exact_decimal():
    prov = provider()

    sale = ask(prov, "blue", "venta")
    purchase = ask(prov, "blue", "compra")

    assert sale.rate == Decimal("1550.25") and purchase.rate == Decimal("1530.5")
    assert (sale.rate_type, sale.side, sale.source) == ("blue", "venta", "dolarapi")
    assert (sale.from_currency, sale.to_currency) == ("USD", "ARS")
    assert sale.quoted_at == datetime(2026, 10, 14, 12, 56, tzinfo=UTC)
    assert sale.stale is False


def test_a_successful_reply_refreshes_the_cache_of_every_rate_type():
    cache = MemoryCache()

    ask(provider(cache=cache), "oficial")

    assert cache.items["oficial"] == CachedQuote(
        "oficial", Decimal("1485"), Decimal("1535"), datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    )
    assert set(cache.items) == {"oficial", "blue"}


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("no route"),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        urllib.error.HTTPError(DOLARAPI_URL, 503, "unavailable", None, None),
    ],
    ids=["unreachable", "timeout", "os error", "http error"],
)
def test_offline_it_falls_back_to_the_last_cached_quote_flagged_as_stale(error):
    cache = MemoryCache()
    ask(provider(cache=cache), "oficial")

    snapshot = ask(provider(FakeTransport(error=error), cache), "oficial", "compra")

    assert snapshot.stale is True
    assert snapshot.rate == Decimal("1485")
    assert snapshot.quoted_at == datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    assert snapshot.source == "dolarapi"


def test_offline_without_a_cached_quote_raises_a_typed_error():
    with pytest.raises(FxUnavailableError):
        ask(provider(FakeTransport(error=urllib.error.URLError("down"))))


def test_the_cache_is_per_rate_type():
    cache = MemoryCache()
    ask(provider(cache=cache), "oficial")

    with pytest.raises(FxUnavailableError):
        ask(provider(FakeTransport(error=TimeoutError()), cache), "mayorista")


@pytest.mark.parametrize(
    "reply",
    [
        b"not json",
        b'{"casa": "oficial"}',
        b'[{"casa":"oficial","compra":1,"venta":0,"fechaActualizacion":"2026-10-14T10:00:00Z"}]',
        b'[{"casa":"oficial","compra":1,"venta":"abc","fechaActualizacion":"2026-10-14T10:00:00Z"}]',
        b'[{"casa":"oficial","compra":1,"venta":2,"fechaActualizacion":"yesterday"}]',
        b'[{"casa":"blue","compra":1,"venta":2,"fechaActualizacion":"2026-10-14T10:00:00Z"}]',
    ],
    ids=["not json", "not a list", "zero rate", "text rate", "bad date", "rate type missing"],
)
def test_an_unusable_reply_without_cache_raises_a_typed_error(reply):
    with pytest.raises(FxInvalidReplyError):
        ask(provider(FakeTransport(reply)))


def test_an_unusable_reply_falls_back_to_the_cache_like_an_outage():
    cache = MemoryCache()
    ask(provider(cache=cache), "oficial")

    snapshot = ask(provider(FakeTransport(b"<html>maintenance</html>"), cache), "oficial")

    assert snapshot.stale is True


def test_only_usd_to_ars_is_published_and_no_request_is_made_for_anything_else():
    transport = FakeTransport()

    with pytest.raises(FxUnsupportedError):
        ask(provider(transport), source="EUR")
    with pytest.raises(FxUnsupportedError):
        ask(provider(transport), target="USD")
    with pytest.raises(FxUnsupportedError):
        ask(provider(transport), rate_type="manual")
    with pytest.raises(FxUnsupportedError):
        ask(provider(transport), side="medio")

    assert transport.calls == []


def test_a_reply_larger_than_any_real_quote_list_is_refused():
    huge = json.dumps([{"casa": "oficial"}] * 50_000).encode()

    with pytest.raises(FxInvalidReplyError):
        ask(provider(FakeTransport(huge)))
