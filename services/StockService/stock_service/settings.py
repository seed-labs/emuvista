"""Runtime settings for Stock Service."""

from __future__ import annotations

import os
import json
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    admin_token: str
    email_host: str
    email_port: int
    email_user: str
    email_password: str
    email_from: str
    email_starttls: bool
    verification_ttl_seconds: int
    quantreplay_host: str
    quantreplay_fix_port: int
    fix_sender_comp_id: str
    fix_target_comp_id: str
    bank_providers: dict[str, dict[str, object]]
    token_encryption_key: str
    allow_test_email_domain: bool

    market_symbols: dict[str, str]
    alpaca_key: str
    alpaca_secret: str
    alpaca_feed: str
    alpaca_https_proxy: str
    market_max_age_seconds: int

    @classmethod
    def from_environment(cls) -> "Settings":
        market_symbols = json.loads(_env("STOCK_MARKET_SYMBOLS") or "{}")
        if not isinstance(market_symbols, dict) or not all(
            isinstance(ticker, str) and ticker.strip() for ticker in market_symbols.values()
        ):
            raise ValueError("STOCK_MARKET_SYMBOLS must map virtual symbols to Alpaca tickers")
        feed = _env("STOCK_ALPACA_FEED", "iex").lower()
        if feed not in {"iex", "sip"}:
            raise ValueError("STOCK_ALPACA_FEED must be iex or sip")
        max_age = int(_env("STOCK_MARKET_MAX_AGE_SECONDS", "120"))
        if max_age <= 0:
            raise ValueError("STOCK_MARKET_MAX_AGE_SECONDS must be positive")
        return cls(
            database_url=_env("STOCK_DATABASE_URL", "postgresql://stock:stock@127.0.0.1:5432/stock"),
            admin_token=_env("STOCK_ADMIN_TOKEN"),
            email_host=_env("STOCK_EMAIL_HOST"),
            email_port=int(_env("STOCK_EMAIL_PORT", "587")),
            email_user=_env("STOCK_EMAIL_USER"),
            email_password=_env("STOCK_EMAIL_PASSWORD"),
            email_from=_env("STOCK_EMAIL_FROM", "stock@seed.example"),
            email_starttls=_env("STOCK_EMAIL_STARTTLS", "true").lower() in {"1", "true", "yes"},
            verification_ttl_seconds=int(_env("STOCK_VERIFICATION_TTL_SECONDS", "900")),
            quantreplay_host=_env("QUANTREPLAY_FIX_HOST"),
            quantreplay_fix_port=int(_env("QUANTREPLAY_FIX_PORT", "9051")),
            fix_sender_comp_id=_env("QUANTREPLAY_FIX_SENDER_COMP_ID", "CLIENT_XETRA"),
            fix_target_comp_id=_env("QUANTREPLAY_FIX_TARGET_COMP_ID", "SIM_XETRA"),
            bank_providers=json.loads(_env("STOCK_BANK_PROVIDERS", "{}")),
            token_encryption_key=_env("STOCK_TOKEN_ENCRYPTION_KEY"),
            allow_test_email_domain=_env("STOCK_ALLOW_TEST_EMAIL_DOMAIN", "false").lower() in {"1", "true", "yes"},
            market_symbols={symbol.upper(): ticker.strip().upper() for symbol, ticker in market_symbols.items()},
            alpaca_key=_env("STOCK_ALPACA_API_KEY"),
            alpaca_secret=_env("STOCK_ALPACA_API_SECRET"),
            alpaca_feed=feed,
            alpaca_https_proxy=_env("STOCK_ALPACA_HTTPS_PROXY"),
            market_max_age_seconds=max_age,
        )


settings = Settings.from_environment()
