from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_execution_engine.integrations.optimizer_targets import (
    OptimizerTargetHandoff,
    OptimizerTargetRow,
    optimizer_targets_to_orders,
)
from trading_execution_engine.integrations.schwab.account_snapshot import (
    SchwabAccountSnapshot,
)
from trading_execution_engine.integrations.schwab.order_preview import (
    build_schwab_order_previews,
)
from trading_execution_engine.models.order import OrderSide


def handoff():
    rows = (
        OptimizerTargetRow(
            symbol="AAA",
            share_delta=-5,
            trade_side="SELL",
            current_position=10,
            target_shares=5,
            reference_price=100.0,
            approved_target_weight=0.25,
            execution_state="DRY_RUN",
        ),
        OptimizerTargetRow(
            symbol="BBB",
            share_delta=10,
            trade_side="BUY",
            current_position=0,
            target_shares=10,
            reference_price=50.0,
            approved_target_weight=0.25,
            execution_state="DRY_RUN",
        ),
        OptimizerTargetRow(
            symbol="CCC",
            share_delta=0,
            trade_side="HOLD",
            current_position=5,
            target_shares=5,
            reference_price=100.0,
            approved_target_weight=0.50,
            execution_state="DRY_RUN",
        ),
    )
    return OptimizerTargetHandoff(
        target_path=Path("execution_safe_targets.csv"),
        manifest_path=Path("manifest.json"),
        artifact_sha256="a" * 64,
        contract_version="portfolio-target-handoff-v1",
        target_builder_version="1.1.0",
        as_of_session="2026-10-16",
        allocation_contract_version="scanner-candidate-allocation-v1",
        allocation_sha256="b" * 64,
        allocation_manifest_sha256="c" * 64,
        scanner_snapshot_sha256="d" * 64,
        positions_sha256="e" * 64,
        portfolio_capital=2000.0,
        execution_state="DRY_RUN",
        rows=rows,
    )


def snapshot(
    *,
    cash=1000.0,
    positions=None,
    prices=None,
):
    return SchwabAccountSnapshot(
        account_hash="HASH-ONE",
        fetched_at_utc=datetime(
            2026, 10, 16, 20, 0, tzinfo=timezone.utc
        ),
        cash_balance=cash,
        available_funds=cash,
        buying_power=cash,
        positions=positions or {"AAA": 10, "CCC": 5},
        prices=prices or {"AAA": 100.0, "BBB": 50.0},
        quote_times_utc={
            "AAA": datetime(
                2026, 10, 16, 19, 59, tzinfo=timezone.utc
            ),
            "BBB": datetime(
                2026, 10, 16, 19, 59, tzinfo=timezone.utc
            ),
        },
        snapshot_sha256="f" * 64,
    )


def test_builds_deterministic_schwab_order_specs():
    target = handoff()
    orders = optimizer_targets_to_orders(target)

    previews = build_schwab_order_previews(
        handoff=target,
        snapshot=snapshot(),
        orders=orders,
    )

    assert [preview.order.side for preview in previews] == [
        OrderSide.SELL,
        OrderSide.BUY,
    ]
    assert all(preview.approved for preview in previews)
    assert all(
        preview.broker_submission_permitted is False
        for preview in previews
    )

    sell_spec = previews[0].schwab_order_spec
    assert sell_spec == {
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": "SELL",
                "quantity": 5,
                "instrument": {
                    "symbol": "AAA",
                    "assetType": "EQUITY",
                },
            }
        ],
    }

    assert previews[0].cash_before == 1000.0
    assert previews[0].cash_after == 1500.0
    assert previews[1].cash_before == 1500.0
    assert previews[1].cash_after == 1000.0


def test_account_position_mismatch_fails_closed():
    target = handoff()
    orders = optimizer_targets_to_orders(target)

    with pytest.raises(ValueError, match="does not match"):
        build_schwab_order_previews(
            handoff=target,
            snapshot=snapshot(positions={"AAA": 9, "CCC": 5}),
            orders=orders,
        )


def test_reference_price_drift_rejects_preview():
    target = handoff()
    orders = optimizer_targets_to_orders(target)

    previews = build_schwab_order_previews(
        handoff=target,
        snapshot=snapshot(prices={"AAA": 100.0, "BBB": 60.0}),
        orders=orders,
        max_reference_price_drift_pct=10.0,
    )

    assert previews[0].approved is True
    assert previews[1].approved is False
    assert previews[1].reason == "reference_price_drift_exceeded"


def test_insufficient_cash_rejects_buy_after_sell_proceeds():
    target = handoff()
    orders = optimizer_targets_to_orders(target)

    previews = build_schwab_order_previews(
        handoff=target,
        snapshot=snapshot(cash=0.0),
        orders=orders,
    )

    assert previews[0].approved is True
    assert previews[0].cash_after == 500.0
    assert previews[1].approved is True
    assert previews[1].cash_after == 0.0


def test_insufficient_cash_rejects_buy_when_quote_is_higher():
    target = handoff()
    orders = optimizer_targets_to_orders(target)

    previews = build_schwab_order_previews(
        handoff=target,
        snapshot=snapshot(
            cash=0.0,
            prices={"AAA": 100.0, "BBB": 55.0},
        ),
        orders=orders,
        max_reference_price_drift_pct=20.0,
    )

    assert previews[0].approved is True
    assert previews[1].approved is False
    assert previews[1].reason == "insufficient_cash"


def test_zero_delta_order_is_never_present():
    target = handoff()
    orders = optimizer_targets_to_orders(target)

    assert [order.symbol for order in orders] == ["AAA", "BBB"]
