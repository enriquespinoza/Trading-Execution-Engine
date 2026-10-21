from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trading_execution_engine.execution_policy.stop_policy import (
    ProtectiveStopType,
    StopPolicy,
    recommend_protective_stop,
)
from trading_execution_engine.integrations.optimizer_targets import (
    OptimizerTargetHandoff,
)
from trading_execution_engine.simulation.persistent_account import (
    PersistentSimulationAccount,
)


STOP_RECOMMENDATION_CONTRACT = "protective-stop-recommendation-v1"

STOP_RECOMMENDATION_COLUMNS = (
    "contract_version",
    "as_of_session",
    "optimizer_artifact_sha256",
    "paper_state_version",
    "paper_state_sha256",
    "symbol",
    "quantity",
    "reference_price",
    "stop_type",
    "stop_price",
    "stop_limit_price",
    "method",
    "stop_distance_pct",
    "stop_limit_buffer_bps",
    "review_only",
    "broker_submission_permitted",
)


@dataclass(frozen=True)
class StopRecommendationArtifact:
    csv_path: Path
    manifest_path: Path
    csv_sha256: str
    row_count: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_positions(values: dict[str, float]) -> dict[str, float]:
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
            "persistent paper positions do not match optimizer "
            f"current_position snapshot; expected={expected}, actual={actual}"
        )


def _write_csv(
    *,
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=STOP_RECOMMENDATION_COLUMNS,
        )
        writer.writeheader()
        writer.writerows(rows)


def build_stop_recommendation_artifact(
    *,
    handoff: OptimizerTargetHandoff,
    state: PersistentSimulationAccount,
    policy: StopPolicy,
    output_dir: str | Path,
    generated_at_utc: datetime | None = None,
) -> StopRecommendationArtifact:
    """
    Export review-only protective stop recommendations for optimizer targets.

    The quantity basis is the optimizer's target_shares. The export does not
    create executable STOP orders and cannot permit broker submission.
    """

    _validate_state_matches_handoff(
        handoff=handoff,
        state=state,
    )

    destination = Path(output_dir)
    if destination.exists():
        raise FileExistsError(
            f"stop recommendation output already exists: {destination}"
        )
    destination.mkdir(parents=True)

    generated = (
        generated_at_utc or datetime.now(timezone.utc)
    ).astimezone(timezone.utc)

    rows: list[dict[str, Any]] = []
    for target in sorted(handoff.rows, key=lambda row: row.symbol):
        if target.target_shares <= 0:
            continue

        recommendation = recommend_protective_stop(
            symbol=target.symbol,
            quantity=target.target_shares,
            reference_price=target.reference_price,
            policy=policy,
        )

        rows.append(
            {
                "contract_version": STOP_RECOMMENDATION_CONTRACT,
                "as_of_session": handoff.as_of_session,
                "optimizer_artifact_sha256": handoff.artifact_sha256,
                "paper_state_version": state.state_version,
                "paper_state_sha256": state.state_sha256,
                "symbol": recommendation.symbol,
                "quantity": recommendation.quantity,
                "reference_price": recommendation.reference_price,
                "stop_type": recommendation.stop_type.value,
                "stop_price": recommendation.stop_price,
                "stop_limit_price": (
                    ""
                    if recommendation.stop_limit_price is None
                    else recommendation.stop_limit_price
                ),
                "method": recommendation.method,
                "stop_distance_pct": policy.stop_distance_pct,
                "stop_limit_buffer_bps": policy.stop_limit_buffer_bps,
                "review_only": True,
                "broker_submission_permitted": False,
            }
        )

    if not rows:
        raise ValueError(
            "optimizer target contains no long positions for stop recommendations"
        )

    csv_path = destination / "protective_stop_recommendations.csv"
    manifest_path = destination / "manifest.json"

    _write_csv(path=csv_path, rows=rows)
    csv_sha = _sha256_file(csv_path)

    manifest = {
        "contract_version": STOP_RECOMMENDATION_CONTRACT,
        "generated_at_utc": generated.isoformat(),
        "as_of_session": handoff.as_of_session,
        "optimizer_artifact_sha256": handoff.artifact_sha256,
        "optimizer_contract_version": handoff.contract_version,
        "paper_state_version": state.state_version,
        "paper_state_sha256": state.state_sha256,
        "row_count": len(rows),
        "stop_type": policy.stop_type.value,
        "method": "fixed_percent",
        "stop_distance_pct": policy.stop_distance_pct,
        "stop_limit_buffer_bps": policy.stop_limit_buffer_bps,
        "quantity_basis": "optimizer_target_shares",
        "protective_stop_recommendations_sha256": csv_sha,
        "immutable": True,
        "review_only": True,
        "broker_submission_permitted": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return StopRecommendationArtifact(
        csv_path=csv_path,
        manifest_path=manifest_path,
        csv_sha256=csv_sha,
        row_count=len(rows),
    )
