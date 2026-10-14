"""Live USD->ARS rates from DolarAPI (https://dolarapi.com), with an offline fallback.

One GET of the public list returns every rate type with `compra` and `venta`; a successful
reply refreshes the cache of all of them. When the request fails, or the reply is unusable,
the last cached quote of the requested rate type is returned flagged `stale` (it keeps its own
date); with no cache the typed error is raised. Standard library only; the transport is
injectable so tests never touch the network. The reply is untrusted data: numbers are parsed as
exact decimals and every field is validated.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from pricor.domain.fx import MARKET_RATE_TYPES, SIDES, TARGET_CURRENCY, FxSnapshot
from pricor.ports.fx_rates import (
    CachedQuote,
    FxInvalidReplyError,
    FxQuoteCache,
    FxUnavailableError,
    FxUnsupportedError,
)

DOLARAPI_URL = "https://dolarapi.com/v1/dolares"
SOURCE = "dolarapi"
DEFAULT_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 200_000
_SOURCE_CURRENCY = "USD"

# (url, timeout seconds) -> raw response body
Transport = Callable[[str, float], bytes]


def urllib_transport(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "pricor/0.1"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read(_MAX_RESPONSE_BYTES + 1)


def _rate(raw: Any, field: str) -> Decimal:
    # JSON numbers are parsed as Decimal; anything else (text, null, bool) is not a rate.
    if not isinstance(raw, Decimal) or not raw.is_finite() or raw <= 0:
        raise FxInvalidReplyError(f"'{field}' is not a positive number")
    return raw


def _parse(raw: bytes) -> dict[str, CachedQuote]:
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise FxInvalidReplyError("the rate list is larger than expected")
    try:
        items = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
    except (ValueError, UnicodeDecodeError) as error:
        raise FxInvalidReplyError("the rate list is not valid JSON") from error
    if not isinstance(items, list):
        raise FxInvalidReplyError("the rate list is not a list")
    quotes: dict[str, CachedQuote] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("casa") not in MARKET_RATE_TYPES:
            continue
        try:
            quoted_at = datetime.fromisoformat(str(item.get("fechaActualizacion")))
        except ValueError as error:
            raise FxInvalidReplyError(f"bad update date for '{item['casa']}'") from error
        if quoted_at.tzinfo is None:
            raise FxInvalidReplyError(f"the update date for '{item['casa']}' has no timezone")
        quotes[item["casa"]] = CachedQuote(
            item["casa"],
            _rate(item.get("compra"), "compra"),
            _rate(item.get("venta"), "venta"),
            quoted_at,
        )
    return quotes


class DolarApiProvider:
    def __init__(
        self,
        transport: Transport = urllib_transport,
        cache: FxQuoteCache | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._transport = transport
        self._cache = cache
        self._timeout = timeout

    def snapshot(
        self, from_currency: str, to_currency: str, rate_type: str, side: str
    ) -> FxSnapshot:
        if (from_currency, to_currency) != (_SOURCE_CURRENCY, TARGET_CURRENCY):
            raise FxUnsupportedError(
                f"DolarAPI only publishes {_SOURCE_CURRENCY} to {TARGET_CURRENCY}, "
                f"not {from_currency} to {to_currency}"
            )
        if rate_type not in MARKET_RATE_TYPES:
            raise FxUnsupportedError(f"DolarAPI has no '{rate_type}' rate")
        if side not in SIDES:
            raise FxUnsupportedError(f"side must be one of: {', '.join(SIDES)}")
        try:
            quote = self._fetch(rate_type)
        except (FxUnavailableError, FxInvalidReplyError):
            cached = None if self._cache is None else self._cache.last(rate_type)
            if cached is None:
                raise
            return replace(self._snapshot(cached, side), stale=True)
        return self._snapshot(quote, side)

    # -- internals -------------------------------------------------------------

    def _fetch(self, rate_type: str) -> CachedQuote:
        try:
            raw = self._transport(DOLARAPI_URL, self._timeout)
        except OSError as error:  # URLError, HTTPError and timeouts are all OSError
            raise FxUnavailableError(f"cannot reach DolarAPI: {error}") from error
        quotes = _parse(raw)
        if self._cache is not None:
            for quote in quotes.values():
                self._cache.save(quote)
        if rate_type not in quotes:
            raise FxInvalidReplyError(f"the rate list has no '{rate_type}' quote")
        return quotes[rate_type]

    @staticmethod
    def _snapshot(quote: CachedQuote, side: str) -> FxSnapshot:
        rate = quote.venta if side == "venta" else quote.compra
        return FxSnapshot(rate, quote.rate_type, side, SOURCE, quote.quoted_at)
