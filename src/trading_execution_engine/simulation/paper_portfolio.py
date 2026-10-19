from __future__ import annotations

import math
from dataclasses import dataclass

from trading_execution_engine.brokers.simulation import (
    SimulationBroker,
    SimulationConfig,
)
from trading_execution_engine.engine import (
    ExecutionControls,
    ExecutionReport,
    ExecutionEngine,
)
from trading_execution_engine.integrations.optimizer_targets import (
    OptimizerTargetHandoff,
    optimizer_targets_to_orders,
)
from trading_execution_engine.integrations.schwab.market_data import (
    SchwabMarketSnapshot,
)
from trading_execution_engine.risk.limits import RiskLimits
from trading_execution_engine.simulation.persistent_account import (
    PersistentSimulationAccount,
    advance_persistent_account,
)


@dataclass(frozen=True)
class PaperPortfolioCycle:
    execution_report: ExecutionReport
    ending_state: PersistentSimulationAccount
    max_reference_price_drift_pct: float
    broker_submission_permitted: bool = False

    def __post_init__(self) -> None:
        if self.broker_submission_permitted:
            raise ValueError(
                "paper portfolio cycle can never permit broker submission"
            )


def _normalized_positions(
    values: dict[str, float],
) -> dict[str, float]:
    return {
        symbol: float(quantity)
        for symbol, quantity in sorted(values.items())
        if abs(float(quantity)) > 1e-12
    }


def _validate_state_matches_handoff(
    *,
    handoff: OptimizerTargetHandoff,
    state: PersistentSimulationAccount,
) -> None:
    expected = _normalized_positions(handoff.current_positions)
    actual = _normalized_positions(state.positions)
    if actual != expected:
        raise ValueError(
            "persistent paper positions do not match optimizer current_position "
            f"snapshot; expected={expected}, actual={actual}"
        )

    if state.source_artifact_sha256 == handoff.artifact_sha256:
        raise ValueError(
            "optimizer artifact has already been applied to persistent state"
        )


def _validate_market_snapshot(
    *,
    handoff: OptimizerTargetHandoff,
    market: SchwabMarketSnapshot,
    max_reference_price_drift_pct: float,
) -> float:
    if not math.isfinite(max_reference_price_drift_pct):
        raise ValueError("max_reference_price_drift_pct must be finite")
    if max_reference_price_drift_pct < 0:
        raise ValueError(
            "max_reference_price_drift_pct cannot be negative"
        )

    required = {row.symbol for row in handoff.rows}
    available = set(market.prices)
    if required != available:
        missing = sorted(required - available)
        extra = sorted(available - required)
        raise ValueError(
            "market snapshot universe does not match optimizer handoff; "
            f"missing={missing}, extra={extra}"
        )

    maximum = 0.0
    for row in handoff.rows:
        market_price = float(market.prices[row.symbol])
        reference_price = float(row.reference_price)
        drift = abs(market_price - reference_price) / reference_price * 100.0
        maximum = max(maximum, drift)
        if drift > max_reference_price_drift_pct:
            raise ValueError(
                "market price drift exceeds configured threshold: "
                f"{row.symbol} drift={drift:.6f}% "
                f"limit={max_reference_price_drift_pct:.6f}%"
            )
    return maximum


def run_paper_portfolio_cycle(
    *,
    handoff: OptimizerTargetHandoff,
    market: SchwabMarketSnapshot,
    state: PersistentSimulationAccount,
    max_order_notional: float = 1_000_000.0,
    max_reference_price_drift_pct: float = 10.0,
    slippage_bps: float = 0.0,
    commission_per_order: float = 0.0,
    commission_per_share: float = 0.0,
) -> PaperPortfolioCycle:
    if handoff.execution_state not in {"DRY_RUN", "PAPER"}:
        raise ValueError(
            "optimizer execution_state must be DRY_RUN or PAPER"
        )

    _validate_state_matches_handoff(
        handoff=handoff,
        state=state,
    )
    max_drift = _validate_market_snapshot(
        handoff=handoff,
        market=market,
        max_reference_price_drift_pct=max_reference_price_drift_pct,
    )

    orders = optimizer_targets_to_orders(handoff)
    account = state.to_account_state()
    broker = SimulationBroker(
        market.prices,
        SimulationConfig(
            slippage_bps=slippage_bps,
            commission_per_order=commission_per_order,
            commission_per_share=commission_per_share,
        ),
    )
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=max_order_notional),
        ExecutionControls(
            allow_fractional_shares=False,
            require_pretrade_notification=False,
            require_pretrade_approval=False,
        ),
    )

    report = engine.execute(
        orders,
        prices=market.prices,
        account=account,
    )

    if report.rejected_count:
        raise ValueError(
            "paper portfolio cycle rejected one or more orders; state not advanced"
        )
    if report.filled_count != len(orders):
        raise ValueError(
            "paper portfolio cycle did not fill every order; state not advanced"
        )

    expected_positions = _normalized_positions(handoff.target_positions)
    actual_positions = _normalized_positions(
        dict(report.ending_positions)
    )
    if actual_positions != expected_positions:
        raise ValueError(
            "paper ending positions do not match optimizer targets; "
            "state not advanced"
        )

    ending_state = advance_persistent_account(
        previous=state,
        account=account,
        source_artifact_sha256=handoff.artifact_sha256,
        market_snapshot_sha256=market.snapshot_sha256,
        order_ids=tuple(order.order_id for order in orders),
    )

    return PaperPortfolioCycle(
        execution_report=report,
        ending_state=ending_state,
        max_reference_price_drift_pct=max_drift,
    )
