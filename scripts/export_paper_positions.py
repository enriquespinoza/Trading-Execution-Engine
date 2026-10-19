from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from trading_execution_engine.integrations.optimizer_state_export import (
    write_optimizer_position_export,
)
from trading_execution_engine.integrations.schwab.market_data import (
    build_schwab_market_snapshot,
)
from trading_execution_engine.simulation.persistent_account import (
    load_persistent_account,
)


def _load_object(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"JSON input not found: {source}")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON input must contain an object: {source}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export the persistent SimulationBroker paper account into the "
            "optimizer's managed-sleeve position contract."
        )
    )
    parser.add_argument(
        "--state",
        default="state/paper_account.json",
    )
    parser.add_argument("--market-capture", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--max-quote-age-minutes",
        type=float,
        default=15.0,
    )
    args = parser.parse_args()

    state = load_persistent_account(args.state)
    capture = _load_object(args.market_capture)

    symbols = capture.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError(
            "market capture must contain a non-empty symbols list"
        )

    market = build_schwab_market_snapshot(
        capture_payload=capture,
        required_symbols=symbols,
        max_quote_age=timedelta(
            minutes=args.max_quote_age_minutes
        ),
    )

    export = write_optimizer_position_export(
        state=state,
        market=market,
        output_dir=args.output_dir,
    )

    print("PERSISTENT PAPER STATE -> OPTIMIZER POSITIONS")
    print("=" * 80)
    print(f"Paper state version: {state.state_version}")
    print(f"Paper state SHA:     {state.state_sha256}")
    print(f"Market snapshot SHA: {market.snapshot_sha256}")
    print(f"Cash:                ${export.cash:,.2f}")
    print(
        f"Position value:      "
        f"${export.position_market_value:,.2f}"
    )
    print(
        f"Portfolio capital:   "
        f"${export.portfolio_capital:,.2f}"
    )
    print(f"Position count:      {export.position_count}")
    print(f"Positions SHA:       {export.positions_sha256}")
    print(f"Manifest SHA:        {export.manifest_sha256}")
    print(f"Positions ->         {export.positions_path}")
    print(f"Manifest ->          {export.manifest_path}")
    print("Broker submission permitted: false")


if __name__ == "__main__":
    main()
