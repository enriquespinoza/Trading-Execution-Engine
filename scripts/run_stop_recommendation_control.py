from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_execution_engine.execution_policy.stop_policy import (
    ProtectiveStopType,
    StopPolicy,
)
from trading_execution_engine.integrations.optimizer_targets import (
    PORTFOLIO_TARGET_HANDOFF_VERSION,
    TARGET_COLUMNS,
    load_optimizer_target_handoff,
    sha256_file,
)
from trading_execution_engine.integrations.stop_recommendations import (
    build_stop_recommendation_artifact,
)
from trading_execution_engine.simulation.persistent_account import (
    advance_persistent_account,
    initialize_persistent_account,
    load_persistent_account,
    save_persistent_account,
)

CONTROL_SESSION = "2026-10-21"
CONTROL_STATE_TIME = datetime(2026, 10, 21, 20, 10, tzinfo=timezone.utc)
CONTROL_GENERATED_TIME = datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    *,
    fieldnames: list[str],
    rows: list[dict[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _target_rows(
    *,
    allocation_sha256: str,
    allocation_manifest_sha256: str,
    scanner_snapshot_sha256: str,
) -> list[dict[str, Any]]:
    common = {
        "handoff_contract_version": PORTFOLIO_TARGET_HANDOFF_VERSION,
        "target_builder_version": "1.2.0-control",
        "as_of_session": CONTROL_SESSION,
        "allocation_contract_version": "scanner-candidate-allocation-v1",
        "allocation_sha256": allocation_sha256,
        "allocation_manifest_sha256": allocation_manifest_sha256,
        "scanner_snapshot_sha256": scanner_snapshot_sha256,
        "portfolio_capital": "10000",
        "execution_state": "PAPER",
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


def generate_control_case(output_root: str | Path) -> dict[str, Any]:
    root = Path(output_root)
    if root.exists():
        raise FileExistsError(f"control output already exists: {root}")

    inputs = root / "inputs"
    artifact_dir = root / "artifact"
    inputs.mkdir(parents=True)

    scanner_snapshot_path = inputs / "scanner_snapshot.json"
    _write_json(
        scanner_snapshot_path,
        {
            "contract": "synthetic-scanner-snapshot-control-v1",
            "session": CONTROL_SESSION,
            "symbols": ["AAA", "BBB"],
        },
    )
    scanner_sha = sha256_file(scanner_snapshot_path)

    allocation_path = inputs / "candidate_allocation.csv"
    _write_csv(
        allocation_path,
        fieldnames=[
            "scanner_rank",
            "symbol",
            "scanner_score",
            "annualized_volatility",
            "target_weight",
        ],
        rows=[
            {
                "scanner_rank": 1,
                "symbol": "AAA",
                "scanner_score": 1.0,
                "annualized_volatility": 0.20,
                "target_weight": 0.60,
            },
            {
                "scanner_rank": 2,
                "symbol": "BBB",
                "scanner_score": 0.8,
                "annualized_volatility": 0.25,
                "target_weight": 0.40,
            },
        ],
    )
    allocation_sha = sha256_file(allocation_path)

    allocation_manifest_path = inputs / "allocation_manifest.json"
    _write_json(
        allocation_manifest_path,
        {
            "contract": "synthetic-allocation-control-v1",
            "session": CONTROL_SESSION,
            "scanner_snapshot_sha256": scanner_sha,
            "candidate_allocation_sha256": allocation_sha,
            "immutable": True,
        },
    )
    allocation_manifest_sha = sha256_file(allocation_manifest_path)

    positions_path = inputs / "current_positions.csv"
    _write_csv(
        positions_path,
        fieldnames=["symbol", "current_position", "reference_price"],
        rows=[
            {"symbol": "AAA", "current_position": 40, "reference_price": 100},
            {"symbol": "BBB", "current_position": 25, "reference_price": 200},
            {"symbol": "CCC", "current_position": 5, "reference_price": 50},
        ],
    )
    positions_sha = sha256_file(positions_path)

    targets_path = inputs / "execution_safe_targets.csv"
    _write_csv(
        targets_path,
        fieldnames=list(TARGET_COLUMNS),
        rows=_target_rows(
            allocation_sha256=allocation_sha,
            allocation_manifest_sha256=allocation_manifest_sha,
            scanner_snapshot_sha256=scanner_sha,
        ),
    )
    target_sha = sha256_file(targets_path)

    target_manifest_path = inputs / "manifest.json"
    _write_json(
        target_manifest_path,
        {
            "handoff_contract_version": PORTFOLIO_TARGET_HANDOFF_VERSION,
            "target_builder_version": "1.2.0-control",
            "as_of_session": CONTROL_SESSION,
            "allocation_contract_version": "scanner-candidate-allocation-v1",
            "allocation_sha256": allocation_sha,
            "allocation_manifest_sha256": allocation_manifest_sha,
            "scanner_snapshot_sha256": scanner_sha,
            "portfolio_capital": 10000.0,
            "execution_state": "PAPER",
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
            "generated_at_utc": "2026-10-21T20:15:00+00:00",
            "immutable": True,
            "broker_submission_permitted": False,
            "positions_sha256": positions_sha,
            "execution_safe_targets_sha256": target_sha,
        },
    )

    prior_optimizer_1 = inputs / "prior_optimizer_v1.json"
    prior_market_1 = inputs / "prior_market_v1.json"
    prior_optimizer_2 = inputs / "prior_optimizer_v2.json"
    prior_market_2 = inputs / "prior_market_v2.json"

    _write_json(prior_optimizer_1, {"fixture": "optimizer-v1"})
    _write_json(prior_market_1, {"fixture": "market-v1"})
    _write_json(prior_optimizer_2, {"fixture": "optimizer-v2"})
    _write_json(prior_market_2, {"fixture": "market-v2"})

    state_v1 = initialize_persistent_account(
        cash=750.0,
        positions={"AAA": 40, "BBB": 25, "CCC": 5},
        updated_at_utc=datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc),
    )
    state_v2 = advance_persistent_account(
        previous=state_v1,
        account=state_v1.to_account_state(),
        source_artifact_sha256=sha256_file(prior_optimizer_1),
        market_snapshot_sha256=sha256_file(prior_market_1),
        order_ids=("control-v1-v2",),
        updated_at_utc=datetime(2026, 10, 21, 20, 5, tzinfo=timezone.utc),
    )
    state_v3 = advance_persistent_account(
        previous=state_v2,
        account=state_v2.to_account_state(),
        source_artifact_sha256=sha256_file(prior_optimizer_2),
        market_snapshot_sha256=sha256_file(prior_market_2),
        order_ids=("control-v2-v3",),
        updated_at_utc=CONTROL_STATE_TIME,
    )
    state_path = inputs / "paper_account.json"
    save_persistent_account(state_v3, state_path)

    handoff = load_optimizer_target_handoff(
        target_csv=targets_path,
        manifest_json=target_manifest_path,
        expected_artifact_sha256=target_sha,
    )
    state = load_persistent_account(state_path)

    artifact = build_stop_recommendation_artifact(
        handoff=handoff,
        state=state,
        policy=StopPolicy(
            stop_type=ProtectiveStopType.STOP_LIMIT,
            stop_distance_pct=8.0,
            stop_limit_buffer_bps=50.0,
        ),
        output_dir=artifact_dir,
        generated_at_utc=CONTROL_GENERATED_TIME,
    )

    with artifact.csv_path.open("r", encoding="utf-8", newline="") as handle:
        recommendation_rows = list(csv.DictReader(handle))

    stop_manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
    observed_csv_sha = sha256_file(artifact.csv_path)

    if observed_csv_sha != artifact.csv_sha256:
        raise RuntimeError("control CSV SHA mismatch")
    if stop_manifest["protective_stop_recommendations_sha256"] != observed_csv_sha:
        raise RuntimeError("control manifest does not pin recommendation CSV")
    if stop_manifest["optimizer_artifact_sha256"] != target_sha:
        raise RuntimeError("control optimizer provenance mismatch")
    if stop_manifest["paper_state_sha256"] != state.state_sha256:
        raise RuntimeError("control paper-state provenance mismatch")

    expected = {
        "AAA": {
            "quantity": "60",
            "reference_price": "100.0",
            "stop_price": "92.0",
            "stop_limit_price": "91.54",
        },
        "BBB": {
            "quantity": "20",
            "reference_price": "200.0",
            "stop_price": "184.0",
            "stop_limit_price": "183.08",
        },
    }
    if [row["symbol"] for row in recommendation_rows] != ["AAA", "BBB"]:
        raise RuntimeError("control recommendation symbols are unexpected")

    for row in recommendation_rows:
        symbol = row["symbol"]
        for field, value in expected[symbol].items():
            if row[field] != value:
                raise RuntimeError(
                    f"control {symbol} {field} mismatch: "
                    f"expected={value} observed={row[field]}"
                )
        if row["review_only"] != "True":
            raise RuntimeError("control recommendation must remain review-only")
        if row["broker_submission_permitted"] != "False":
            raise RuntimeError("control recommendation must forbid broker submission")

    return {
        "root": root,
        "recommendation_csv_path": artifact.csv_path,
        "recommendation_manifest_path": artifact.manifest_path,
        "optimizer_artifact_sha256": target_sha,
        "paper_state_sha256": state.state_sha256,
        "recommendation_csv_sha256": observed_csv_sha,
        "row_count": artifact.row_count,
        "rows": recommendation_rows,
        "manifest": stop_manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate and validate a deterministic synthetic protective-stop "
            "recommendation artifact before using real paper state."
        )
    )
    parser.add_argument(
        "--output-root",
        default="reports/validation/stop_recommendations/control/2026-10-21",
    )
    args = parser.parse_args()

    result = generate_control_case(args.output_root)

    print("CONTROLLED PROTECTIVE STOP VALIDATION")
    print("=" * 80)
    print(f"Root:               {result['root']}")
    print(f"Optimizer SHA:      {result['optimizer_artifact_sha256']}")
    print(f"Paper state SHA:    {result['paper_state_sha256']}")
    print(f"Rows:               {result['row_count']}")
    print(f"Recommendation SHA: {result['recommendation_csv_sha256']}")
    print()
    print("RECOMMENDATIONS")
    print("-" * 80)
    for row in result["rows"]:
        print(
            f"{row['symbol']:8} qty={row['quantity']:>4} "
            f"ref={row['reference_price']:>8} "
            f"stop={row['stop_price']:>8} "
            f"stop_limit={row['stop_limit_price']:>8} "
            "review_only=true broker_submission=false"
        )
    print()
    print("PROVENANCE")
    print("-" * 80)
    manifest = result["manifest"]
    print(
        "CSV SHA matches manifest: "
        + str(
            manifest["protective_stop_recommendations_sha256"]
            == result["recommendation_csv_sha256"]
        )
    )
    print(
        "Optimizer SHA matches manifest: "
        + str(
            manifest["optimizer_artifact_sha256"]
            == result["optimizer_artifact_sha256"]
        )
    )
    print(
        "Paper-state SHA matches manifest: "
        + str(
            manifest["paper_state_sha256"]
            == result["paper_state_sha256"]
        )
    )
    print("Review only:        " + str(manifest["review_only"]).lower())
    print(
        "Broker submission:  "
        + str(manifest["broker_submission_permitted"]).lower()
    )
    print()
    print(f"CSV:                {result['recommendation_csv_path']}")
    print(f"Manifest:           {result['recommendation_manifest_path']}")
    print()
    print(
        "PASS: controlled stop-recommendation artifact and provenance "
        "validated. Real state-v3 input has not been touched."
    )


if __name__ == "__main__":
    main()
