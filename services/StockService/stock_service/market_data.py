"""Read-only US stock snapshots shared by the dashboard and system purchases."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock
from time import monotonic
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen


logger = logging.getLogger(__name__)
PRICE_INCREMENT = Decimal("0.00000001")


def _price(value: object) -> Decimal | None:
    if not isinstance(value, (int, Decimal)) or isinstance(value, bool):
        return None
    price = Decimal(value)
    if not price.is_finite() or not 0 < price < 10**12:
        return None
    return price.quantize(PRICE_INCREMENT) or None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


@dataclass(frozen=True)
class Snapshot:
    last_trade_price: Decimal | None
    last_trade_at: datetime | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    quoted_at: datetime | None


@dataclass(frozen=True)
class CachedSnapshot:
    snapshot: Snapshot | None
    checked_at: datetime | None
    refresh_after: float
    healthy: bool


class AlpacaMarketData:
    def __init__(
        self, symbols: dict[str, str], key: str, secret: str, feed: str, max_age_seconds: int,
        *, https_proxy: str = "",
    ):
        self.symbols = symbols
        self.key = key
        self.secret = secret
        self.feed = feed
        self.max_age = timedelta(seconds=max_age_seconds)
        self.proxy_opener = build_opener(ProxyHandler({"https": https_proxy})) if https_proxy else None
        self.cache: dict[str, CachedSnapshot] = {}
        self.lock = Lock()

    def _fetch(self, ticker: str) -> Snapshot:
        url = f"https://data.alpaca.markets/v2/stocks/{quote(ticker, safe='')}/snapshot"
        request = Request(url + "?" + urlencode({"feed": self.feed}), headers={
            "Accept": "application/json",
            "APCA-API-KEY-ID": self.key,
            "APCA-API-SECRET-KEY": self.secret,
        })
        open_request = self.proxy_opener.open if self.proxy_opener else urlopen
        with open_request(request, timeout=3) as response:
            data = json.loads(response.read(65536), parse_float=Decimal)
        trade = data.get("latestTrade") or {}
        quote_data = data.get("latestQuote") or {}
        return Snapshot(
            _price(trade.get("p")), _timestamp(trade.get("t")),
            _price(quote_data.get("bp")), _price(quote_data.get("ap")), _timestamp(quote_data.get("t")),
        )

    def _snapshot(self, ticker: str) -> CachedSnapshot:
        with self.lock:
            previous = self.cache.get(ticker)
            if previous and monotonic() < previous.refresh_after:
                return previous
            try:
                snapshot = self._fetch(ticker)
            except (OSError, ValueError, TypeError, AttributeError) as error:
                logger.warning("Alpaca snapshot unavailable for %s (%s)", ticker, type(error).__name__)
                entry = CachedSnapshot(
                    previous.snapshot if previous else None, previous.checked_at if previous else None,
                    monotonic() + 5, False,
                )
            else:
                entry = CachedSnapshot(snapshot, datetime.now(timezone.utc), monotonic() + 2, True)
            self.cache[ticker] = entry
            return entry

    def quote(self, symbol: str) -> dict:
        ticker = self.symbols.get(symbol)
        configured = bool(ticker and self.key and self.secret)
        entry = self._snapshot(ticker) if configured else None
        snapshot = entry.snapshot if entry and entry.snapshot else Snapshot(None, None, None, None, None)
        checked_at = entry.checked_at if entry else None
        now = datetime.now(timezone.utc)
        # The last trade can be much older than a successful market-data check.
        current_feed = bool(entry and entry.healthy and checked_at
                            and -timedelta(seconds=5) <= now - checked_at <= self.max_age)

        def freshness(timestamp: datetime | None, available: bool) -> str:
            if not configured:
                return "not_configured"
            if timestamp is None or timestamp > now + timedelta(seconds=5) or not available:
                return "unavailable"
            return "live" if current_feed else "stale"

        bid, ask = snapshot.best_bid, snapshot.best_ask
        return {
            "source": f"alpaca:{self.feed}" if ticker else None,
            "provider_symbol": ticker,
            "checked_at": checked_at,
            "best_bid": bid,
            "best_ask": ask,
            "spread": ask - bid if ask is not None and bid is not None else None,
            "quoted_at": snapshot.quoted_at,
            "quote_status": freshness(snapshot.quoted_at, bid is not None and ask is not None),
            "last_trade_price": snapshot.last_trade_price,
            "last_trade_at": snapshot.last_trade_at,
            "trade_status": freshness(snapshot.last_trade_at, snapshot.last_trade_price is not None),
        }
