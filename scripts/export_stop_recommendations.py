from __future__ import annotations

import argparse
from pathlib import Path

from trading_execution_engine.execution_policy.stop_policy import (
    ProtectiveStopType,
    StopPolicy,
)
from trading_execution_engine.integrations.optimizer_targets import (
    load_optimizer_target_handoff,
)
from trading_execution_engine.integrations.stop_recommendations import (
    build_stop_recommendation_artifact,
)
from trading_execution_engine.simulation.persistent_account import (
    load_persistent_account,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export immutable, review-only protective stop recommendations "
            "from a verified optimizer target and persistent paper state."
        )
    )
    parser.add_argument("--targets", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument(
        "--state",
        default="state/paper_account.json",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--stop-type",
        choices=[value.value for value in ProtectiveStopType],
        default=ProtectiveStopType.STOP_LIMIT.value,
    )
    parser.add_argument(
        "--stop-distance-pct",
        type=float,
        default=8.0,
    )
    parser.add_argument(
        "--stop-limit-buffer-bps",
        type=float,
        default=50.0,
    )
    args = parser.parse_args()

    handoff = load_optimizer_target_handoff(
        target_csv=args.targets,
        manifest_json=args.manifest,
        expected_artifact_sha256=args.expected_sha256,
    )
    state = load_persistent_account(args.state)

    stop_type = ProtectiveStopType(args.stop_type)
    buffer_bps = (
        0.0
        if stop_type == ProtectiveStopType.STOP
        else args.stop_limit_buffer_bps
    )
    policy = StopPolicy(
        stop_type=stop_type,
        stop_distance_pct=args.stop_distance_pct,
        stop_limit_buffer_bps=buffer_bps,
    )

    artifact = build_stop_recommendation_artifact(
        handoff=handoff,
        state=state,
        policy=policy,
        output_dir=Path(args.output_dir),
    )

    print("PROTECTIVE STOP RECOMMENDATION EXPORT")
    print("=" * 80)
    print(f"Optimizer session:  {handoff.as_of_session}")
    print(f"Optimizer SHA:      {handoff.artifact_sha256}")
    print(f"Paper state:        v{state.state_version}")
    print(f"Paper state SHA:    {state.state_sha256}")
    print(f"Rows:               {artifact.row_count}")
    print(f"Stop type:          {policy.stop_type.value}")
    print(f"Stop distance:      {policy.stop_distance_pct:.4f}%")
    print(
        "Stop-limit buffer: "
        f"{policy.stop_limit_buffer_bps:.4f} bps"
    )
    print(f"CSV SHA:            {artifact.csv_sha256}")
    print(f"CSV:                {artifact.csv_path}")
    print(f"Manifest:           {artifact.manifest_path}")
    print("Review only:        true")
    print("Broker submission:  false")


if __name__ == "__main__":
    main()
