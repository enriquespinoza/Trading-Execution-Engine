from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from trading_execution_engine.integrations.optimizer_targets import (
    load_optimizer_target_handoff,
)
from trading_execution_engine.integrations.schwab.market_data import (
    build_schwab_market_snapshot,
)
from trading_execution_engine.simulation.paper_portfolio import (
    run_paper_portfolio_cycle,
)
from trading_execution_engine.simulation.persistent_account import (
    initialize_persistent_account,
    load_persistent_account,
    save_persistent_account,
)


def _load_object(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"JSON input not found: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON input must contain an object: {source}")
    return payload


def _write_report(path: str | Path, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Execute optimizer targets through SimulationBroker using "
            "Schwab market-data prices and a persistent local paper account. "
            "No Schwab account or trading endpoint is used."
        )
    )
    parser.add_argument("--targets", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--market-capture", required=True)
    parser.add_argument(
        "--state",
        default="state/paper_account.json",
    )
    parser.add_argument(
        "--initialize-state",
        action="store_true",
        help=(
            "Initialize the persistent paper state if it does not yet exist. "
            "--initial-cash is required."
        ),
    )
    parser.add_argument("--initial-cash", type=float)
    parser.add_argument(
        "--max-quote-age-minutes",
        type=float,
        default=15.0,
    )
    parser.add_argument(
        "--max-reference-price-drift-pct",
        type=float,
        default=10.0,
    )
    parser.add_argument(
        "--max-order-notional",
        type=float,
        default=1_000_000.0,
    )
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument(
        "--commission-per-order",
        type=float,
        default=0.0,
    )
    parser.add_argument(
        "--commission-per-share",
        type=float,
        default=0.0,
    )
    parser.add_argument("--output-report")
    args = parser.parse_args()

    handoff = load_optimizer_target_handoff(
        target_csv=args.targets,
        manifest_json=args.manifest,
        expected_artifact_sha256=args.expected_sha256,
    )

    market = build_schwab_market_snapshot(
        capture_payload=_load_object(args.market_capture),
        required_symbols=[row.symbol for row in handoff.rows],
        max_quote_age=timedelta(
            minutes=args.max_quote_age_minutes
        ),
    )

    state_path = Path(args.state)
    if state_path.exists():
        if args.initialize_state:
            raise SystemExit(
                "FAIL: --initialize-state cannot overwrite existing paper state."
            )
        state = load_persistent_account(state_path)
    else:
        if not args.initialize_state:
            raise SystemExit(
                "FAIL: persistent paper state does not exist. "
                "Use --initialize-state with explicit --initial-cash."
            )
        if args.initial_cash is None:
            raise SystemExit(
                "FAIL: --initial-cash is required when initializing state."
            )
        state = initialize_persistent_account(
            cash=args.initial_cash,
            positions=handoff.current_positions,
        )
        save_persistent_account(state, state_path)

    print("SCHWAB MARKET DATA -> PERSISTENT SIMULATIONBROKER")
    print("=" * 80)
    print(f"Optimizer session:  {handoff.as_of_session}")
    print(f"Optimizer SHA:      {handoff.artifact_sha256}")
    print(f"Market snapshot:    {market.snapshot_sha256}")
    print(f"State version:      {state.state_version}")
    print(f"State SHA:          {state.state_sha256}")
    print(f"Starting cash:      ${state.cash:,.2f}")
    print(f"Starting positions: {state.positions}")
    print("Schwab account API: NOT USED")
    print("Schwab trading API: NOT USED")
    print("External submission: false")

    cycle = run_paper_portfolio_cycle(
        handoff=handoff,
        market=market,
        state=state,
        max_order_notional=args.max_order_notional,
        max_reference_price_drift_pct=(
            args.max_reference_price_drift_pct
        ),
        slippage_bps=args.slippage_bps,
        commission_per_order=args.commission_per_order,
        commission_per_share=args.commission_per_share,
    )

    report = cycle.execution_report

    print()
    print("SIMULATED EXECUTION")
    print("-" * 80)
    for result in report.results:
        fill_price = (
            f"${result.fill.fill_price:,.4f}"
            if result.fill is not None
            else "-"
        )
        print(
            f"{result.order.side.value:4} "
            f"{result.order.quantity:g} "
            f"{result.order.symbol:8} "
            f"{result.status.value:16} "
            f"fill={fill_price} "
            f"{result.execution_reason}"
        )

    save_persistent_account(
        cycle.ending_state,
        state_path,
    )

    print()
    print(f"Ending cash:        ${cycle.ending_state.cash:,.2f}")
    print(f"Ending positions:   {cycle.ending_state.positions}")
    print(f"New state version:  {cycle.ending_state.state_version}")
    print(f"New state SHA:      {cycle.ending_state.state_sha256}")
    print(
        "Max price drift:   "
        f"{cycle.max_reference_price_drift_pct:.4f}%"
    )

    output = {
        "validation_contract": "market-data-paper-simulation-v1",
        "optimizer": {
            "as_of_session": handoff.as_of_session,
            "artifact_sha256": handoff.artifact_sha256,
            "handoff_contract_version": handoff.contract_version,
            "target_builder_version": handoff.target_builder_version,
        },
        "market": {
            "snapshot_sha256": market.snapshot_sha256,
            "captured_at_utc": market.captured_at_utc.isoformat(),
            "price_fields": market.price_fields,
        },
        "simulation": {
            "broker": "SimulationBroker",
            "starting_state_sha256": state.state_sha256,
            "ending_state_sha256": cycle.ending_state.state_sha256,
            "state_version": cycle.ending_state.state_version,
            "starting_cash": report.starting_cash,
            "ending_cash": report.ending_cash,
            "ending_positions": dict(report.ending_positions),
            "filled_count": report.filled_count,
            "rejected_count": report.rejected_count,
            "max_reference_price_drift_pct": (
                cycle.max_reference_price_drift_pct
            ),
            "slippage_bps": args.slippage_bps,
            "commission_per_order": args.commission_per_order,
            "commission_per_share": args.commission_per_share,
            "external_broker_submission": False,
        },
        "orders": [
            {
                "order_id": result.order.order_id,
                "symbol": result.order.symbol,
                "side": result.order.side.value,
                "quantity": result.order.quantity,
                "status": result.status.value,
                "fill_price": (
                    result.fill.fill_price
                    if result.fill is not None
                    else None
                ),
                "fees": (
                    result.fill.fees
                    if result.fill is not None
                    else None
                ),
            }
            for result in report.results
        ],
    }

    if args.output_report:
        _write_report(args.output_report, output)
        print(f"Report:             {args.output_report}")

    print()
    print(
        "PASS: Schwab market data drove a persistent SimulationBroker "
        "paper-portfolio cycle."
    )
    print("No Schwab account or trading endpoint was called.")


if __name__ == "__main__":
    main()
