from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from trading_execution_engine.execution_policy.policy import (
    ExecutionOrderPolicy,
)
from trading_execution_engine.integrations.optimizer_targets import (
    PORTFOLIO_TARGET_HANDOFF_VERSION,
    TARGET_COLUMNS,
    load_optimizer_target_handoff,
    optimizer_targets_to_orders,
)
from trading_execution_engine.models.order import OrderSide, OrderType


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_targets(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def base_rows() -> list[dict]:
    common = {
        "handoff_contract_version": PORTFOLIO_TARGET_HANDOFF_VERSION,
        "target_builder_version": "1.1.0",
        "as_of_session": "2026-10-16",
        "allocation_contract_version": "scanner-candidate-allocation-v1",
        "allocation_sha256": "a" * 64,
        "allocation_manifest_sha256": "b" * 64,
        "scanner_snapshot_sha256": "c" * 64,
        "portfolio_capital": "10000",
        "execution_state": "DRY_RUN",
    }

    return [
        {
            **common,
            "symbol": "AAA",
            "scanner_rank": "1",
            "approved_target_weight": "0.60",
            "reference_price": "100",
            "reference_price_source": "scanner_allocation_close",
            "target_dollar_value": "6000",
            "target_shares": "60",
            "target_share_notional": "6000",
            "realized_target_weight": "0.60",
            "weight_rounding_error": "0",
            "target_status": "TARGETED",
            "current_position": "40",
            "share_delta": "20",
            "trade_side": "BUY",
        },
        {
            **common,
            "symbol": "BBB",
            "scanner_rank": "2",
            "approved_target_weight": "0.40",
            "reference_price": "200",
            "reference_price_source": "scanner_allocation_close",
            "target_dollar_value": "4000",
            "target_shares": "20",
            "target_share_notional": "4000",
            "realized_target_weight": "0.40",
            "weight_rounding_error": "0",
            "target_status": "TARGETED",
            "current_position": "25",
            "share_delta": "-5",
            "trade_side": "SELL",
        },
        {
            **common,
            "symbol": "CCC",
            "scanner_rank": "",
            "approved_target_weight": "0",
            "reference_price": "50",
            "reference_price_source": "position_snapshot",
            "target_dollar_value": "0",
            "target_shares": "0",
            "target_share_notional": "0",
            "realized_target_weight": "0",
            "weight_rounding_error": "0",
            "target_status": "EXIT",
            "current_position": "5",
            "share_delta": "-5",
            "trade_side": "SELL",
        },
    ]


def write_bundle(
    tmp_path: Path,
    *,
    rows: list[dict] | None = None,
    manifest_overrides: dict | None = None,
):
    target_path = tmp_path / "execution_safe_targets.csv"
    manifest_path = tmp_path / "manifest.json"

    rows = rows or base_rows()
    write_targets(target_path, rows)
    artifact_sha = sha256(target_path)

    manifest = {
        "handoff_contract_version": PORTFOLIO_TARGET_HANDOFF_VERSION,
        "target_builder_version": "1.1.0",
        "as_of_session": "2026-10-16",
        "allocation_contract_version": "scanner-candidate-allocation-v1",
        "allocation_sha256": "a" * 64,
        "allocation_manifest_sha256": "b" * 64,
        "scanner_snapshot_sha256": "c" * 64,
        "portfolio_capital": 10000.0,
        "execution_state": "DRY_RUN",
        "share_rounding_policy": "floor_nonnegative_whole_shares",
        "row_count": 3,
        "target_symbol_count": 2,
        "targeted_count": 2,
        "zero_weight_count": 0,
        "rounding_to_zero_count": 0,
        "exit_count": 1,
        "buy_count": 1,
        "sell_count": 2,
        "hold_count": 0,
        "target_notional": 10000.0,
        "residual_cash": 0.0,
        "realized_weight_sum": 1.0,
        "total_weight_rounding_error": 0.0,
        "generated_at_utc": "2026-10-16T20:00:00+00:00",
        "immutable": True,
        "broker_submission_permitted": False,
        "positions_sha256": "d" * 64,
        "execution_safe_targets_sha256": artifact_sha,
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target_path, manifest_path, artifact_sha


def test_valid_handoff_loads_and_orders_are_deterministic(tmp_path):
    target_path, manifest_path, artifact_sha = write_bundle(tmp_path)

    handoff = load_optimizer_target_handoff(
        target_csv=target_path,
        manifest_json=manifest_path,
        expected_artifact_sha256=artifact_sha,
    )
    orders = optimizer_targets_to_orders(handoff)

    assert handoff.execution_state == "DRY_RUN"
    assert handoff.artifact_sha256 == artifact_sha

    assert [(o.symbol, o.side, o.quantity) for o in orders] == [
        ("BBB", OrderSide.SELL, 5.0),
        ("CCC", OrderSide.SELL, 5.0),
        ("AAA", OrderSide.BUY, 20.0),
    ]
    assert all(order.order_type == OrderType.MARKET for order in orders)

    second = optimizer_targets_to_orders(handoff)
    assert [order.order_id for order in orders] == [
        order.order_id for order in second
    ]


def test_zero_delta_creates_no_order(tmp_path):
    rows = base_rows()
    rows[0]["current_position"] = "60"
    rows[0]["share_delta"] = "0"
    rows[0]["trade_side"] = "HOLD"

    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
        manifest_overrides={
            "buy_count": 0,
            "sell_count": 2,
            "hold_count": 1,
        },
    )

    handoff = load_optimizer_target_handoff(
        target_csv=target_path,
        manifest_json=manifest_path,
    )
    orders = optimizer_targets_to_orders(handoff)

    assert [order.symbol for order in orders] == ["BBB", "CCC"]


@pytest.mark.parametrize("state", ["LIVE", "SIMULATION", ""])
def test_rejects_invalid_execution_state(tmp_path, state):
    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        manifest_overrides={"execution_state": state},
    )

    with pytest.raises(ValueError, match="DRY_RUN or PAPER"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_accepts_paper_state(tmp_path):
    rows = base_rows()
    for row in rows:
        row["execution_state"] = "PAPER"

    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        rows=rows,
        manifest_overrides={"execution_state": "PAPER"},
    )

    handoff = load_optimizer_target_handoff(
        target_csv=target_path,
        manifest_json=manifest_path,
    )
    assert handoff.execution_state == "PAPER"


def test_rejects_broker_submission_permission(tmp_path):
    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        manifest_overrides={"broker_submission_permitted": True},
    )

    with pytest.raises(ValueError, match="broker_submission_permitted"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_wrong_contract_version(tmp_path):
    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        manifest_overrides={
            "handoff_contract_version": "portfolio-target-handoff-v2"
        },
    )

    with pytest.raises(ValueError, match="contract mismatch"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_manifest_artifact_sha_mismatch(tmp_path):
    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        manifest_overrides={
            "execution_safe_targets_sha256": "f" * 64
        },
    )

    with pytest.raises(ValueError, match="artifact SHA-256 mismatch"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_pinned_artifact_sha_mismatch(tmp_path):
    target_path, manifest_path, _ = write_bundle(tmp_path)

    with pytest.raises(ValueError, match="pinned SHA-256"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
            expected_artifact_sha256="f" * 64,
        )


def test_rejects_tampered_share_delta(tmp_path):
    rows = base_rows()
    rows[0]["share_delta"] = "999"

    target_path, manifest_path, _ = write_bundle(tmp_path, rows=rows)

    with pytest.raises(ValueError, match="share_delta must equal"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_trade_side_mismatch(tmp_path):
    rows = base_rows()
    rows[0]["trade_side"] = "SELL"

    target_path, manifest_path, _ = write_bundle(tmp_path, rows=rows)

    with pytest.raises(ValueError, match="trade_side"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_manifest_count_mismatch(tmp_path):
    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        manifest_overrides={"buy_count": 99},
    )

    with pytest.raises(ValueError, match="buy_count mismatch"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_row_manifest_execution_state_mismatch(tmp_path):
    rows = base_rows()
    rows[1]["execution_state"] = "PAPER"

    target_path, manifest_path, _ = write_bundle(tmp_path, rows=rows)

    with pytest.raises(ValueError, match="execution_state does not match"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_rejects_non_immutable_manifest(tmp_path):
    target_path, manifest_path, _ = write_bundle(
        tmp_path,
        manifest_overrides={"immutable": False},
    )

    with pytest.raises(ValueError, match="immutable"):
        load_optimizer_target_handoff(
            target_csv=target_path,
            manifest_json=manifest_path,
        )


def test_optimizer_order_policy_can_emit_limits(tmp_path):
    target_path, manifest_path, artifact_sha = write_bundle(tmp_path)

    handoff = load_optimizer_target_handoff(
        target_csv=target_path,
        manifest_json=manifest_path,
        expected_artifact_sha256=artifact_sha,
    )

    orders = optimizer_targets_to_orders(
        handoff,
        execution_policy=ExecutionOrderPolicy(
            use_limit_orders=True,
            buy_limit_tolerance_bps=25,
            sell_limit_tolerance_bps=50,
        ),
    )

    assert [(o.symbol, o.side, o.quantity) for o in orders] == [
        ("BBB", OrderSide.SELL, 5.0),
        ("CCC", OrderSide.SELL, 5.0),
        ("AAA", OrderSide.BUY, 20.0),
    ]

    assert all(order.order_type == OrderType.LIMIT for order in orders)

    by_symbol = {order.symbol: order for order in orders}

    assert by_symbol["BBB"].limit_price == 199.0
    assert by_symbol["CCC"].limit_price == 49.75
    assert by_symbol["AAA"].limit_price == 100.25

    second = optimizer_targets_to_orders(
        handoff,
        execution_policy=ExecutionOrderPolicy(
            use_limit_orders=True,
            buy_limit_tolerance_bps=25,
            sell_limit_tolerance_bps=50,
        ),
    )

    assert [order.order_id for order in orders] == [
        order.order_id for order in second
    ]
