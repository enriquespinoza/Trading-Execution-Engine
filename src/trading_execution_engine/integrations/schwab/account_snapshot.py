from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_MAX_QUOTE_AGE = timedelta(minutes=5)


@dataclass(frozen=True)
class SchwabAccountSnapshot:
    """Normalized read-only Schwab account and quote state."""

    account_hash: str
    fetched_at_utc: datetime
    cash_balance: float
    available_funds: float | None
    buying_power: float | None
    positions: dict[str, int]
    prices: dict[str, float]
    quote_times_utc: dict[str, datetime]
    snapshot_sha256: str
    broker_submission_permitted: bool = False

    def __post_init__(self) -> None:
        if self.broker_submission_permitted:
            raise ValueError(
                "SchwabAccountSnapshot can never permit broker submission"
            )


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


def _optional_nonnegative_float(
    mapping: Mapping[str, Any],
    key: str,
) -> float | None:
    if key not in mapping or mapping[key] is None:
        return None
    value = _finite_float(mapping[key], key)
    if value < 0:
        raise ValueError(f"{key} cannot be negative")
    return value


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
        raise ValueError(f"{field} must be ISO-8601 or epoch time") from exc

    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _extract_account(account_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    root = _mapping(account_payload, "account_payload")
    account = root.get("securitiesAccount", root)
    return _mapping(account, "securitiesAccount")


def _extract_positions(account: Mapping[str, Any]) -> dict[str, int]:
    raw_positions = account.get("positions", [])
    if raw_positions is None:
        raw_positions = []
    if not isinstance(raw_positions, Sequence) or isinstance(
        raw_positions, (str, bytes)
    ):
        raise ValueError("positions must be a sequence")

    positions: dict[str, int] = {}
    for index, raw in enumerate(raw_positions):
        position = _mapping(raw, f"positions[{index}]")
        instrument = _mapping(
            position.get("instrument"),
            f"positions[{index}].instrument",
        )
        symbol = str(instrument.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError(f"positions[{index}] missing symbol")
        if symbol in positions:
            raise ValueError(f"duplicate Schwab position: {symbol}")

        long_qty = _finite_float(
            position.get("longQuantity", 0.0),
            f"{symbol}.longQuantity",
        )
        short_qty = _finite_float(
            position.get("shortQuantity", 0.0),
            f"{symbol}.shortQuantity",
        )
        if long_qty < 0 or short_qty < 0:
            raise ValueError(f"{symbol} position quantities cannot be negative")
        if short_qty > 1e-12:
            raise ValueError(
                f"short positions are not supported by this preflight: {symbol}"
            )
        if not float(long_qty).is_integer():
            raise ValueError(
                f"fractional positions are not supported by this preflight: {symbol}"
            )

        quantity = int(long_qty)
        if quantity:
            positions[symbol] = quantity

    return positions


def _quote_record(
    quote_payload: Mapping[str, Any],
    symbol: str,
) -> Mapping[str, Any]:
    direct = quote_payload.get(symbol)
    if direct is None:
        direct = quote_payload.get(symbol.upper())
    if direct is None:
        raise ValueError(f"Schwab quote response missing symbol: {symbol}")

    record = _mapping(direct, f"quote_payload[{symbol}]")
    quote = record.get("quote", record)
    return _mapping(quote, f"quote_payload[{symbol}].quote")


def _extract_quote(
    quote_payload: Mapping[str, Any],
    symbol: str,
) -> tuple[float, datetime]:
    quote = _quote_record(quote_payload, symbol)

    price_value = None
    for field in ("lastPrice", "mark", "closePrice", "bidPrice", "askPrice"):
        value = quote.get(field)
        if value is not None:
            candidate = _finite_float(value, f"{symbol}.{field}")
            if candidate > 0:
                price_value = candidate
                break

    if price_value is None:
        raise ValueError(f"Schwab quote has no positive price for {symbol}")

    time_value = None
    for field in ("quoteTime", "tradeTime", "regularMarketTradeTime"):
        if quote.get(field) is not None:
            time_value = quote[field]
            break
    if time_value is None:
        raise ValueError(f"Schwab quote has no timestamp for {symbol}")

    return price_value, _timestamp(time_value, f"{symbol}.quoteTime")


def _snapshot_hash(
    *,
    cash_balance: float,
    available_funds: float | None,
    buying_power: float | None,
    positions: Mapping[str, int],
    prices: Mapping[str, float],
    quote_times: Mapping[str, datetime],
) -> str:
    payload = {
        "cash_balance": cash_balance,
        "available_funds": available_funds,
        "buying_power": buying_power,
        "positions": dict(sorted(positions.items())),
        "prices": dict(sorted(prices.items())),
        "quote_times_utc": {
            symbol: value.astimezone(timezone.utc).isoformat()
            for symbol, value in sorted(quote_times.items())
        },
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_schwab_account_snapshot(
    *,
    account_hash: str,
    account_payload: Mapping[str, Any],
    quote_payload: Mapping[str, Any],
    required_symbols: Sequence[str],
    fetched_at_utc: datetime | str,
    max_quote_age: timedelta = DEFAULT_MAX_QUOTE_AGE,
) -> SchwabAccountSnapshot:
    account_hash = str(account_hash).strip()
    if not account_hash:
        raise ValueError("account_hash is required")

    fetched_at = (
        fetched_at_utc
        if isinstance(fetched_at_utc, datetime)
        else _timestamp(fetched_at_utc, "fetched_at_utc")
    )
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at_utc must be timezone-aware")
    fetched_at = fetched_at.astimezone(timezone.utc)

    if max_quote_age <= timedelta(0):
        raise ValueError("max_quote_age must be positive")

    account = _extract_account(account_payload)
    balances = _mapping(
        account.get("currentBalances"),
        "currentBalances",
    )
    if "cashBalance" not in balances:
        raise ValueError("currentBalances missing cashBalance")

    cash_balance = _finite_float(
        balances["cashBalance"],
        "cashBalance",
    )
    if cash_balance < 0:
        raise ValueError("cashBalance cannot be negative")

    available_funds = _optional_nonnegative_float(
        balances,
        "availableFunds",
    )
    buying_power = _optional_nonnegative_float(
        balances,
        "buyingPower",
    )
    positions = _extract_positions(account)

    symbols = [
        str(symbol).strip().upper()
        for symbol in required_symbols
    ]
    if not symbols or any(not symbol for symbol in symbols):
        raise ValueError("required_symbols cannot be empty")
    if len(symbols) != len(set(symbols)):
        raise ValueError("required_symbols cannot contain duplicates")

    quotes = _mapping(quote_payload, "quote_payload")
    prices: dict[str, float] = {}
    quote_times: dict[str, datetime] = {}

    for symbol in symbols:
        price, quote_time = _extract_quote(quotes, symbol)
        if quote_time > fetched_at:
            raise ValueError(
                f"quote timestamp is later than snapshot time for {symbol}"
            )
        if fetched_at - quote_time > max_quote_age:
            raise ValueError(f"stale Schwab quote for {symbol}")

        prices[symbol] = price
        quote_times[symbol] = quote_time

    digest = _snapshot_hash(
        cash_balance=cash_balance,
        available_funds=available_funds,
        buying_power=buying_power,
        positions=positions,
        prices=prices,
        quote_times=quote_times,
    )

    return SchwabAccountSnapshot(
        account_hash=account_hash,
        fetched_at_utc=fetched_at,
        cash_balance=cash_balance,
        available_funds=available_funds,
        buying_power=buying_power,
        positions=positions,
        prices=prices,
        quote_times_utc=quote_times,
        snapshot_sha256=digest,
    )
