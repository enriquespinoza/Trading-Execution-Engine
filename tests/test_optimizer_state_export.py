from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest

from trading_execution_engine.integrations.optimizer_state_export import (
    POSITION_SNAPSHOT_CONTRACT,
    build_optimizer_position_rows,
    write_optimizer_position_export,
)
from trading_execution_engine.integrations.schwab.market_data import (
    build_schwab_market_snapshot,
)
from trading_execution_engine.simulation.persistent_account import (
    initialize_persistent_account,
)


NOW = datetime(
    2026, 10, 19, 18, 0, tzinfo=timezone.utc
)


def market_snapshot():
    quote_time = int(
        datetime(
            2026, 10, 19, 17, 59, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )
    return build_schwab_market_snapshot(
        capture_payload={
            "capture_contract": "schwab-market-data-capture-v1",
            "captured_at_utc": NOW.isoformat(),
            "symbols": ["AAA", "BBB"],
            "quotes": {
                "AAA": {
                    "quote": {
                        "lastPrice": 100.0,
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
        },
        required_symbols=["AAA", "BBB"],
    )


def paper_state():
    return initialize_persistent_account(
        cash=1000.0,
        positions={"AAA": 5, "BBB": 10},
        updated_at_utc=NOW,
    )


def test_build_rows_and_portfolio_market_value():
    rows, market_value = build_optimizer_position_rows(
        state=paper_state(),
        market=market_snapshot(),
    )

    assert rows == [
        {
            "symbol": "AAA",
            "current_position": 5,
            "reference_price": 100.0,
        },
        {
            "symbol": "BBB",
            "current_position": 10,
            "reference_price": 50.0,
        },
    ]
    assert market_value == 1000.0


def test_write_export_manifest_and_csv(tmp_path):
    export = write_optimizer_position_export(
        state=paper_state(),
        market=market_snapshot(),
        output_dir=tmp_path / "export",
        generated_at_utc=NOW,
    )

    assert export.portfolio_capital == 2000.0
    assert export.cash == 1000.0
    assert export.position_market_value == 1000.0
    assert export.position_count == 2

    with export.positions_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert rows == [
        {
            "symbol": "AAA",
            "current_position": "5",
            "reference_price": "100.0",
        },
        {
            "symbol": "BBB",
            "current_position": "10",
            "reference_price": "50.0",
        },
    ]

    manifest = json.loads(
        export.manifest_path.read_text(encoding="utf-8")
    )
    assert (
        manifest["position_snapshot_contract"]
        == POSITION_SNAPSHOT_CONTRACT
    )
    assert manifest["portfolio_capital"] == 2000.0
    assert manifest["cash"] == 1000.0
    assert manifest["position_market_value"] == 1000.0
    assert manifest["position_count"] == 2
    assert manifest["immutable"] is True
    assert manifest["broker_submission_permitted"] is False
    assert manifest["positions_sha256"] == export.positions_sha256


def test_missing_market_price_for_held_position_rejected():
    market = market_snapshot()
    object.__setattr__(
        market,
        "prices",
        {"AAA": 100.0},
    )

    with pytest.raises(ValueError, match="missing held"):
        build_optimizer_position_rows(
            state=paper_state(),
            market=market,
        )


def test_writer_refuses_overwrite(tmp_path):
    output = tmp_path / "export"

    write_optimizer_position_export(
        state=paper_state(),
        market=market_snapshot(),
        output_dir=output,
        generated_at_utc=NOW,
    )

    with pytest.raises(FileExistsError, match="already exists"):
        write_optimizer_position_export(
            state=paper_state(),
            market=market_snapshot(),
            output_dir=output,
            generated_at_utc=NOW,
        )
