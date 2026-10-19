from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


CAPTURE_CONTRACT = "schwab-market-data-capture-v1"
SNAPSHOT_CONTRACT = "schwab-market-snapshot-v1"
DEFAULT_MAX_QUOTE_AGE = timedelta(minutes=15)
PRICE_FIELD_PRIORITY = (
    "mark",
    "lastPrice",
    "closePrice",
)


@dataclass(frozen=True)
class SchwabMarketSnapshot:
    contract_version: str
    captured_at_utc: datetime
    prices: dict[str, float]
    price_fields: dict[str, str]
    quote_times_utc: dict[str, datetime]
    snapshot_sha256: str

    def __post_init__(self) -> None:
        if self.contract_version != SNAPSHOT_CONTRACT:
            raise ValueError("unsupported Schwab market snapshot contract")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be a mapping")
    return value


def _finite_float(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{field} must be finite")
        seconds = numeric / 1000.0 if abs(numeric) >= 1e11 else numeric
        return datetime.fromtimestamp(seconds, tz=timezone.utc)

    text = str(value).strip()
    if not text:
        raise ValueError(f"{field} cannot be empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"{field} must be timezone-aware ISO-8601 or epoch time"
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    normalized = [str(symbol).strip().upper() for symbol in symbols]
    if not normalized or any(not symbol for symbol in normalized):
        raise ValueError("required_symbols cannot be empty")
    if len(normalized) != len(set(normalized)):
        raise ValueError("required_symbols cannot contain duplicates")
    return normalized


def _quote_record(
    quotes: Mapping[str, Any],
    symbol: str,
) -> Mapping[str, Any]:
    row = quotes.get(symbol)
    if row is None:
        row = quotes.get(symbol.upper())
    if row is None:
        raise ValueError(f"Schwab quote capture missing symbol: {symbol}")
    record = _mapping(row, f"quotes[{symbol}]")
    quote = record.get("quote", record)
    return _mapping(quote, f"quotes[{symbol}].quote")


def _extract_price(
    quote: Mapping[str, Any],
    symbol: str,
) -> tuple[float, str]:
    for field in PRICE_FIELD_PRIORITY:
        value = quote.get(field)
        if value is None:
            continue
        price = _finite_float(value, f"{symbol}.{field}")
        if price > 0:
            return price, field
    raise ValueError(
        f"Schwab quote has no positive execution reference price for {symbol}"
    )


def _extract_quote_time(
    quote: Mapping[str, Any],
    symbol: str,
) -> datetime:
    for field in (
        "quoteTime",
        "tradeTime",
        "regularMarketTradeTime",
    ):
        if quote.get(field) is not None:
            return _timestamp(quote[field], f"{symbol}.{field}")
    raise ValueError(f"Schwab quote has no timestamp for {symbol}")


def _snapshot_sha256(
    *,
    captured_at_utc: datetime,
    prices: Mapping[str, float],
    price_fields: Mapping[str, str],
    quote_times_utc: Mapping[str, datetime],
) -> str:
    payload = {
        "contract_version": SNAPSHOT_CONTRACT,
        "captured_at_utc": captured_at_utc.isoformat(),
        "prices": dict(sorted(prices.items())),
        "price_fields": dict(sorted(price_fields.items())),
        "quote_times_utc": {
            symbol: timestamp.isoformat()
            for symbol, timestamp in sorted(quote_times_utc.items())
        },
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_schwab_market_snapshot(
    *,
    capture_payload: Mapping[str, Any],
    required_symbols: Sequence[str],
    max_quote_age: timedelta = DEFAULT_MAX_QUOTE_AGE,
) -> SchwabMarketSnapshot:
    capture = _mapping(capture_payload, "capture_payload")

    contract = str(
        capture.get("capture_contract", "")
    ).strip()
    if contract != CAPTURE_CONTRACT:
        raise ValueError(
            f"capture_contract must be {CAPTURE_CONTRACT}"
        )

    captured_at = _timestamp(
        capture.get("captured_at_utc"),
        "captured_at_utc",
    )
    if max_quote_age <= timedelta(0):
        raise ValueError("max_quote_age must be positive")

    required = _normalize_symbols(required_symbols)
    declared_symbols = _normalize_symbols(
        capture.get("symbols", [])
    )
    if set(declared_symbols) != set(required):
        raise ValueError(
            "capture symbols do not exactly match the optimizer target universe"
        )

    quotes = _mapping(capture.get("quotes"), "quotes")
    returned = {
        str(key).strip().upper()
        for key in quotes.keys()
    }
    missing = sorted(set(required) - returned)
    if missing:
        raise ValueError(
            "Schwab quote capture missing requested symbols: "
            + ", ".join(missing)
        )

    prices: dict[str, float] = {}
    price_fields: dict[str, str] = {}
    quote_times: dict[str, datetime] = {}

    for symbol in sorted(required):
        quote = _quote_record(quotes, symbol)
        price, field = _extract_price(quote, symbol)
        quote_time = _extract_quote_time(quote, symbol)

        if quote_time > captured_at:
            raise ValueError(
                f"quote timestamp is later than capture time for {symbol}"
            )
        if captured_at - quote_time > max_quote_age:
            raise ValueError(f"stale Schwab quote for {symbol}")

        prices[symbol] = price
        price_fields[symbol] = field
        quote_times[symbol] = quote_time

    digest = _snapshot_sha256(
        captured_at_utc=captured_at,
        prices=prices,
        price_fields=price_fields,
        quote_times_utc=quote_times,
    )

    return SchwabMarketSnapshot(
        contract_version=SNAPSHOT_CONTRACT,
        captured_at_utc=captured_at,
        prices=prices,
        price_fields=price_fields,
        quote_times_utc=quote_times,
        snapshot_sha256=digest,
    )
