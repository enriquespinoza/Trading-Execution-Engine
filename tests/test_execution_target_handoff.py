from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal

import pytest

from trading_execution_engine.handoff.execution_target import (
    ExecutionState,
    build_execution_target,
    write_execution_target,
)


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_inputs(tmp_path):
    allocation = tmp_path / "candidate_allocation.csv"
    prices = tmp_path / "reference_prices.csv"
    positions = tmp_path / "current_positions.csv"

    write_csv(
        allocation,
        [
            "scanner_rank",
            "symbol",
            "scanner_score",
            "annualized_volatility",
            "target_weight",
        ],
        [
            {
                "scanner_rank": 1,
                "symbol": "AAA",
                "scanner_score": "0.90",
                "annualized_volatility": "0.20",
                "target_weight": "0.60",
            },
            {
                "scanner_rank": 2,
                "symbol": "BBB",
                "scanner_score": "0.80",
                "annualized_volatility": "0.25",
                "target_weight": "0.40",
            },
        ],
    )
    write_csv(
        prices,
        ["symbol", "reference_price"],
        [
            {"symbol": "AAA", "reference_price": "100"},
            {"symbol": "BBB", "reference_price": "250"},
            {"symbol": "OLD", "reference_price": "50"},
        ],
    )
    write_csv(
        positions,
        ["symbol", "current_position"],
        [
            {"symbol": "AAA", "current_position": "30"},
            {"symbol": "BBB", "current_position": "20"},
            {"symbol": "OLD", "current_position": "10"},
        ],
    )
    return allocation, prices, positions


def test_builds_execution_safe_target_and_liquidation_row(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)

    build = build_execution_target(
        allocation_csv=allocation,
        reference_prices_csv=prices,
        current_positions_csv=positions,
        portfolio_capital="10000",
        execution_state="DRY_RUN",
    )

    assert build.allocation_sha256 == sha256(allocation)
    assert build.execution_state == ExecutionState.DRY_RUN
    assert build.portfolio_capital == Decimal("10000")

    by_symbol = {row.symbol: row for row in build.rows}

    aaa = by_symbol["AAA"]
    assert aaa.approved_target_weight == Decimal("0.60")
    assert aaa.reference_price == Decimal("100")
    assert aaa.target_dollar_value == Decimal("6000.00")
    assert aaa.target_shares == 60
    assert aaa.current_position == 30
    assert aaa.share_delta == 30

    bbb = by_symbol["BBB"]
    assert bbb.target_dollar_value == Decimal("4000.00")
    assert bbb.target_shares == 16
    assert bbb.current_position == 20
    assert bbb.share_delta == -4

    old = by_symbol["OLD"]
    assert old.approved_target_weight == Decimal("0")
    assert old.target_dollar_value == Decimal("0.00")
    assert old.target_shares == 0
    assert old.current_position == 10
    assert old.share_delta == -10


def test_whole_share_floor_is_deterministic(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)

    build = build_execution_target(
        allocation_csv=allocation,
        reference_prices_csv=prices,
        current_positions_csv=positions,
        portfolio_capital="9999",
        execution_state="PAPER",
    )
    by_symbol = {row.symbol: row for row in build.rows}

    assert by_symbol["AAA"].target_shares == 59
    assert by_symbol["BBB"].target_shares == 15
    assert all(
        row.execution_state == ExecutionState.PAPER
        for row in build.rows
    )


def test_rejects_allocation_sha_mismatch(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        build_execution_target(
            allocation_csv=allocation,
            reference_prices_csv=prices,
            current_positions_csv=positions,
            portfolio_capital="10000",
            execution_state="DRY_RUN",
            expected_allocation_sha256="0" * 64,
        )


def test_rejects_weights_that_do_not_sum_to_one(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)

    rows = list(csv.DictReader(allocation.open(encoding="utf-8")))
    rows[1]["target_weight"] = "0.30"
    write_csv(
        allocation,
        [
            "scanner_rank",
            "symbol",
            "scanner_score",
            "annualized_volatility",
            "target_weight",
        ],
        rows,
    )

    with pytest.raises(ValueError, match="must sum to 1"):
        build_execution_target(
            allocation_csv=allocation,
            reference_prices_csv=prices,
            current_positions_csv=positions,
            portfolio_capital="10000",
            execution_state="DRY_RUN",
        )


def test_rejects_missing_reference_price(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)
    write_csv(
        prices,
        ["symbol", "reference_price"],
        [{"symbol": "AAA", "reference_price": "100"}],
    )

    with pytest.raises(ValueError, match="missing reference prices"):
        build_execution_target(
            allocation_csv=allocation,
            reference_prices_csv=prices,
            current_positions_csv=positions,
            portfolio_capital="10000",
            execution_state="DRY_RUN",
        )


def test_rejects_live_execution_state(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)

    with pytest.raises(
        ValueError,
        match="must be DRY_RUN or PAPER",
    ):
        build_execution_target(
            allocation_csv=allocation,
            reference_prices_csv=prices,
            current_positions_csv=positions,
            portfolio_capital="10000",
            execution_state="LIVE",
        )


def test_writes_exact_contract_and_manifest(tmp_path):
    allocation, prices, positions = make_inputs(tmp_path)
    output = tmp_path / "execution_target.csv"
    manifest = tmp_path / "execution_target.manifest.json"

    build = build_execution_target(
        allocation_csv=allocation,
        reference_prices_csv=prices,
        current_positions_csv=positions,
        portfolio_capital="10000",
        execution_state="PAPER",
    )
    write_execution_target(
        build=build,
        output_csv=output,
        manifest_json=manifest,
    )

    with output.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
            "allocation_sha256",
            "symbol",
            "approved_target_weight",
            "reference_price",
            "portfolio_capital",
            "target_dollar_value",
            "target_shares",
            "current_position",
            "share_delta",
            "execution_state",
        ]
        rows = list(reader)

    assert rows[0]["allocation_sha256"] == sha256(allocation)
    assert rows[0]["execution_state"] == "PAPER"

    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    assert metadata["execution_target_contract"] == "execution-target-v1"
    assert metadata["execution_state"] == "PAPER"
    assert metadata["live_execution_allowed"] is False
    assert metadata["allocation_sha256"] == sha256(allocation)
    assert metadata["execution_target_sha256"] == sha256(output)
