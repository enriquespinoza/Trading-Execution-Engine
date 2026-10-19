from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trading_execution_engine.integrations.schwab.market_data import (
    build_schwab_market_snapshot,
)


CAPTURED = datetime(
    2026, 10, 19, 15, 0, tzinfo=timezone.utc
)


def capture_payload():
    quote_time = int(
        datetime(
            2026, 10, 19, 14, 59, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )
    return {
        "capture_contract": "schwab-market-data-capture-v1",
        "captured_at_utc": CAPTURED.isoformat(),
        "symbols": ["AAA", "BBB"],
        "quotes": {
            "AAA": {
                "quote": {
                    "mark": 101.0,
                    "lastPrice": 100.5,
                    "quoteTime": quote_time,
                }
            },
            "BBB": {
                "quote": {
                    "lastPrice": 50.0,
                    "quoteTime": quote_time,
                }
            },
        },
    }


def test_builds_market_snapshot_deterministically():
    first = build_schwab_market_snapshot(
        capture_payload=capture_payload(),
        required_symbols=["AAA", "BBB"],
    )
    second = build_schwab_market_snapshot(
        capture_payload=capture_payload(),
        required_symbols=["AAA", "BBB"],
    )

    assert first.prices == {"AAA": 101.0, "BBB": 50.0}
    assert first.price_fields == {
        "AAA": "mark",
        "BBB": "lastPrice",
    }
    assert first.snapshot_sha256 == second.snapshot_sha256


def test_universe_must_match_exactly():
    with pytest.raises(ValueError, match="exactly match"):
        build_schwab_market_snapshot(
            capture_payload=capture_payload(),
            required_symbols=["AAA"],
        )


def test_stale_quote_rejected():
    payload = capture_payload()
    payload["quotes"]["AAA"]["quote"]["quoteTime"] = int(
        (CAPTURED - timedelta(minutes=20)).timestamp()
        * 1000
    )

    with pytest.raises(ValueError, match="stale"):
        build_schwab_market_snapshot(
            capture_payload=payload,
            required_symbols=["AAA", "BBB"],
            max_quote_age=timedelta(minutes=15),
        )


def test_future_quote_rejected():
    payload = capture_payload()
    payload["quotes"]["AAA"]["quote"]["quoteTime"] = int(
        (CAPTURED + timedelta(seconds=1)).timestamp()
        * 1000
    )

    with pytest.raises(ValueError, match="later than"):
        build_schwab_market_snapshot(
            capture_payload=payload,
            required_symbols=["AAA", "BBB"],
        )


def test_nonpositive_quote_rejected():
    payload = capture_payload()
    payload["quotes"]["BBB"]["quote"]["lastPrice"] = 0.0

    with pytest.raises(ValueError, match="no positive"):
        build_schwab_market_snapshot(
            capture_payload=payload,
            required_symbols=["AAA", "BBB"],
        )


def test_wrong_capture_contract_rejected():
    payload = capture_payload()
    payload["capture_contract"] = "wrong"

    with pytest.raises(ValueError, match="capture_contract"):
        build_schwab_market_snapshot(
            capture_payload=payload,
            required_symbols=["AAA", "BBB"],
        )
