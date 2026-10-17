from __future__ import annotations

import argparse
from decimal import Decimal

from trading_execution_engine.handoff.execution_target import (
    ExecutionState,
    build_execution_target,
    write_execution_target,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert scanner candidate_allocation.csv into an "
            "execution-safe target artifact."
        )
    )
    parser.add_argument("--allocation", required=True)
    parser.add_argument("--prices", required=True)
    parser.add_argument("--positions", required=True)
    parser.add_argument("--capital", required=True)
    parser.add_argument(
        "--state",
        required=True,
        choices=[state.value for state in ExecutionState],
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--expected-allocation-sha256")

    args = parser.parse_args()

    build = build_execution_target(
        allocation_csv=args.allocation,
        reference_prices_csv=args.prices,
        current_positions_csv=args.positions,
        portfolio_capital=Decimal(args.capital),
        execution_state=args.state,
        expected_allocation_sha256=args.expected_allocation_sha256,
    )
    output_path, manifest_path = write_execution_target(
        build=build,
        output_csv=args.output,
        manifest_json=args.manifest,
    )

    print("EXECUTION TARGET BUILT")
    print("=" * 72)
    print(f"Allocation SHA: {build.allocation_sha256}")
    print(f"State:          {build.execution_state.value}")
    print(f"Capital:        ${build.portfolio_capital:,.2f}")
    print(f"Rows:           {len(build.rows)}")
    print(f"CSV:            {output_path}")
    print(f"Manifest:       {manifest_path}")


if __name__ == "__main__":
    main()
