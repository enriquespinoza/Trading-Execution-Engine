from __future__ import annotations

import argparse

from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionControls, ExecutionEngine
from trading_execution_engine.integrations.optimizer_targets import (
    load_optimizer_target_handoff,
    optimizer_targets_to_orders,
)
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.risk.limits import RiskLimits


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate portfolio-target-handoff-v1 and execute the resulting "
            "orders only through SimulationBroker."
        )
    )
    parser.add_argument("--targets", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument(
        "--max-order-notional",
        type=float,
        default=1_000_000.0,
    )
    args = parser.parse_args()

    handoff = load_optimizer_target_handoff(
        target_csv=args.targets,
        manifest_json=args.manifest,
        expected_artifact_sha256=args.expected_sha256,
    )
    orders = optimizer_targets_to_orders(handoff)

    print("OPTIMIZER TARGET HANDOFF")
    print("=" * 72)
    print(f"Contract:       {handoff.contract_version}")
    print(f"Builder:        {handoff.target_builder_version}")
    print(f"Session:        {handoff.as_of_session}")
    print(f"Execution:      {handoff.execution_state}")
    print(f"Artifact SHA:   {handoff.artifact_sha256}")
    print(f"Capital:        ${handoff.portfolio_capital:,.2f}")
    print(f"Order count:    {len(orders)}")
    print()
    print("PROPOSED ORDERS")
    print("-" * 72)

    if not orders:
        print("No orders required.")
    else:
        for order in orders:
            print(
                f"{order.side.value:4} "
                f"{order.quantity:g} "
                f"{order.symbol:8} "
                f"order_id={order.order_id}"
            )

    account = AccountState(
        cash=handoff.portfolio_capital
        - sum(
            row.current_position * row.reference_price
            for row in handoff.rows
        ),
        positions=handoff.current_positions,
    )
    if account.cash < -1e-8:
        raise SystemExit(
            "FAIL: reconstructed starting cash is negative; "
            "handoff accounting is inconsistent."
        )

    broker = SimulationBroker(handoff.reference_prices)
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=args.max_order_notional),
        ExecutionControls(
            allow_fractional_shares=False,
            require_pretrade_notification=False,
            require_pretrade_approval=False,
        ),
    )

    report = engine.execute(
        orders,
        prices=handoff.reference_prices,
        account=account,
    )

    print()
    print("SIMULATION RESULTS")
    print("-" * 72)
    for result in report.results:
        print(
            f"{result.order.side.value:4} "
            f"{result.order.quantity:g} "
            f"{result.order.symbol:8} "
            f"{result.status.value:16} "
            f"{result.execution_reason}"
        )

    expected_positions = handoff.target_positions
    actual_positions = {
        symbol: quantity
        for symbol, quantity in report.ending_positions.items()
        if abs(quantity) > 1e-12
    }

    print()
    print(f"Starting cash: ${report.starting_cash:,.2f}")
    print(f"Ending cash:   ${report.ending_cash:,.2f}")
    print(f"Positions:     {actual_positions}")

    if report.rejected_count:
        raise SystemExit("FAIL: one or more simulated orders were rejected.")

    if actual_positions != expected_positions:
        raise SystemExit(
            "FAIL: simulated ending positions do not match optimizer targets."
        )

    print()
    print(
        "PASS: portfolio-target-handoff-v1 validated and converted "
        "deterministically into SimulationBroker orders."
    )
    print("No external broker submission occurred.")


if __name__ == "__main__":
    main()
