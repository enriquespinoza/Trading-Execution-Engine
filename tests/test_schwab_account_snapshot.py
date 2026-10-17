from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_execution_engine.integrations.schwab.account_snapshot import (
    build_schwab_account_snapshot,
)


FETCHED_AT = datetime(
    2026, 10, 16, 20, 0, tzinfo=timezone.utc
)


def account_payload():
    return {
        "securitiesAccount": {
            "currentBalances": {
                "cashBalance": 50000.0,
                "availableFunds": 50000.0,
                "buyingPower": 100000.0,
            },
            "positions": [
                {
                    "instrument": {"symbol": "AMD"},
                    "longQuantity": 10.0,
                    "shortQuantity": 0.0,
                },
                {
                    "instrument": {"symbol": "HPE"},
                    "longQuantity": 20.0,
                    "shortQuantity": 0.0,
                },
            ],
        }
    }


def quote_payload():
    quote_time = int(
        datetime(
            2026, 10, 16, 19, 59, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )
    return {
        "AMD": {
            "quote": {
                "lastPrice": 205.0,
                "quoteTime": quote_time,
            }
        },
        "HPE": {
            "quote": {
                "lastPrice": 25.0,
                "quoteTime": quote_time,
            }
        },
    }


def test_builds_read_only_snapshot():
    snapshot = build_schwab_account_snapshot(
        account_hash="HASH-ONE",
        account_payload=account_payload(),
        quote_payload=quote_payload(),
        required_symbols=["AMD", "HPE"],
        fetched_at_utc=FETCHED_AT,
    )

    assert snapshot.cash_balance == 50000.0
    assert snapshot.available_funds == 50000.0
    assert snapshot.buying_power == 100000.0
    assert snapshot.positions == {"AMD": 10, "HPE": 20}
    assert snapshot.prices == {"AMD": 205.0, "HPE": 25.0}
    assert snapshot.broker_submission_permitted is False
    assert len(snapshot.snapshot_sha256) == 64


def test_snapshot_hash_is_deterministic():
    kwargs = {
        "account_hash": "HASH-ONE",
        "account_payload": account_payload(),
        "quote_payload": quote_payload(),
        "required_symbols": ["AMD", "HPE"],
        "fetched_at_utc": FETCHED_AT,
    }

    first = build_schwab_account_snapshot(**kwargs)
    second = build_schwab_account_snapshot(**kwargs)

    assert first.snapshot_sha256 == second.snapshot_sha256


def test_missing_cash_rejected():
    payload = account_payload()
    del payload["securitiesAccount"]["currentBalances"]["cashBalance"]

    with pytest.raises(ValueError, match="cashBalance"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=payload,
            quote_payload=quote_payload(),
            required_symbols=["AMD", "HPE"],
            fetched_at_utc=FETCHED_AT,
        )


def test_short_position_rejected():
    payload = account_payload()
    payload["securitiesAccount"]["positions"][0]["shortQuantity"] = 1.0

    with pytest.raises(ValueError, match="short positions"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=payload,
            quote_payload=quote_payload(),
            required_symbols=["AMD", "HPE"],
            fetched_at_utc=FETCHED_AT,
        )


def test_fractional_position_rejected():
    payload = account_payload()
    payload["securitiesAccount"]["positions"][0]["longQuantity"] = 10.5

    with pytest.raises(ValueError, match="fractional"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=payload,
            quote_payload=quote_payload(),
            required_symbols=["AMD", "HPE"],
            fetched_at_utc=FETCHED_AT,
        )


def test_missing_required_quote_rejected():
    quotes = quote_payload()
    del quotes["HPE"]

    with pytest.raises(ValueError, match="HPE"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=account_payload(),
            quote_payload=quotes,
            required_symbols=["AMD", "HPE"],
            fetched_at_utc=FETCHED_AT,
        )


def test_stale_quote_rejected():
    quotes = quote_payload()
    quotes["AMD"]["quote"]["quoteTime"] = int(
        (
            FETCHED_AT - timedelta(minutes=10)
        ).timestamp()
        * 1000
    )

    with pytest.raises(ValueError, match="stale"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=account_payload(),
            quote_payload=quotes,
            required_symbols=["AMD", "HPE"],
            fetched_at_utc=FETCHED_AT,
            max_quote_age=timedelta(minutes=5),
        )


def test_future_quote_rejected():
    quotes = quote_payload()
    quotes["AMD"]["quote"]["quoteTime"] = int(
        (
            FETCHED_AT + timedelta(seconds=1)
        ).timestamp()
        * 1000
    )

    with pytest.raises(ValueError, match="later than"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=account_payload(),
            quote_payload=quotes,
            required_symbols=["AMD", "HPE"],
            fetched_at_utc=FETCHED_AT,
        )


def test_duplicate_required_symbol_rejected():
    with pytest.raises(ValueError, match="duplicates"):
        build_schwab_account_snapshot(
            account_hash="HASH-ONE",
            account_payload=account_payload(),
            quote_payload=quote_payload(),
            required_symbols=["AMD", "AMD"],
            fetched_at_utc=FETCHED_AT,
        )
