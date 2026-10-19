from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_execution_engine.integrations.optimizer_targets import (
    OptimizerTargetHandoff,
    OptimizerTargetRow,
)
from trading_execution_engine.integrations.schwab.market_data import (
    build_schwab_market_snapshot,
)
from trading_execution_engine.simulation.paper_portfolio import (
    run_paper_portfolio_cycle,
)
from trading_execution_engine.simulation.persistent_account import (
    advance_persistent_account,
    initialize_persistent_account,
)
from trading_execution_engine.models.account import AccountState


CAPTURED = datetime(
    2026, 10, 19, 15, 0, tzinfo=timezone.utc
)


def build_handoff(
    *,
    artifact_sha="a" * 64,
    current_aaa=10,
):
    rows = (
        OptimizerTargetRow(
            symbol="AAA",
            share_delta=-5,
            trade_side="SELL",
            current_position=current_aaa,
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
    )
    return OptimizerTargetHandoff(
        target_path=Path("execution_safe_targets.csv"),
        manifest_path=Path("manifest.json"),
        artifact_sha256=artifact_sha,
        contract_version="portfolio-target-handoff-v1",
        target_builder_version="1.1.0",
        as_of_session="2026-10-19",
        allocation_contract_version="scanner-candidate-allocation-v1",
        allocation_sha256="b" * 64,
        allocation_manifest_sha256="c" * 64,
        scanner_snapshot_sha256="d" * 64,
        positions_sha256="e" * 64,
        portfolio_capital=2000.0,
        execution_state="DRY_RUN",
        rows=rows,
    )


def market(aaa=100.0, bbb=50.0):
    quote_time = int(
        datetime(
            2026, 10, 19, 14, 59, tzinfo=timezone.utc
        ).timestamp()
        * 1000
    )
    payload = {
        "capture_contract": "schwab-market-data-capture-v1",
        "captured_at_utc": CAPTURED.isoformat(),
        "symbols": ["AAA", "BBB"],
        "quotes": {
            "AAA": {
                "quote": {
                    "lastPrice": aaa,
                    "quoteTime": quote_time,
                }
            },
            "BBB": {
                "quote": {
                    "lastPrice": bbb,
                    "quoteTime": quote_time,
                }
            },
        },
    }
    return build_schwab_market_snapshot(
        capture_payload=payload,
        required_symbols=["AAA", "BBB"],
    )


def initial_state():
    return initialize_persistent_account(
        cash=1000.0,
        positions={"AAA": 10},
        updated_at_utc=CAPTURED,
    )


def test_successful_cycle_uses_market_prices_and_advances_state():
    cycle = run_paper_portfolio_cycle(
        handoff=build_handoff(),
        market=market(),
        state=initial_state(),
    )

    assert cycle.execution_report.filled_count == 2
    assert cycle.execution_report.rejected_count == 0
    assert cycle.ending_state.cash == 1000.0
    assert cycle.ending_state.positions == {
        "AAA": 5.0,
        "BBB": 10.0,
    }
    assert cycle.ending_state.state_version == 2
    assert cycle.ending_state.previous_state_sha256 == (
        initial_state().state_sha256
    )
    assert cycle.broker_submission_permitted is False


def test_persistent_positions_must_match_optimizer():
    with pytest.raises(ValueError, match="do not match"):
        run_paper_portfolio_cycle(
            handoff=build_handoff(current_aaa=9),
            market=market(),
            state=initial_state(),
        )


def test_price_drift_blocks_before_execution():
    with pytest.raises(ValueError, match="price drift"):
        run_paper_portfolio_cycle(
            handoff=build_handoff(),
            market=market(bbb=60.0),
            state=initial_state(),
            max_reference_price_drift_pct=10.0,
        )


def test_replay_of_applied_artifact_is_rejected():
    original = initial_state()
    previously_applied = advance_persistent_account(
        previous=original,
        account=AccountState(
            cash=1000.0,
            positions={"AAA": 10},
        ),
        source_artifact_sha256="a" * 64,
        market_snapshot_sha256="f" * 64,
        order_ids=("old-order",),
        updated_at_utc=CAPTURED,
    )

    with pytest.raises(ValueError, match="already been applied"):
        run_paper_portfolio_cycle(
            handoff=build_handoff(),
            market=market(),
            state=previously_applied,
        )


def test_insufficient_cash_blocks_state_advance():
    state = initialize_persistent_account(
        cash=0.0,
        positions={"AAA": 10},
        updated_at_utc=CAPTURED,
    )

    with pytest.raises(ValueError, match="rejected"):
        run_paper_portfolio_cycle(
            handoff=build_handoff(),
            market=market(aaa=100.0, bbb=60.0),
            state=state,
            max_reference_price_drift_pct=25.0,
        )
