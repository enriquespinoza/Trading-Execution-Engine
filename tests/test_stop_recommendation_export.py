from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trading_execution_engine.execution_policy.stop_policy import (
    ProtectiveStopType,
    StopPolicy,
)
from trading_execution_engine.integrations.optimizer_targets import (
    OptimizerTargetHandoff,
    OptimizerTargetRow,
)
from trading_execution_engine.integrations.stop_recommendations import (
    STOP_RECOMMENDATION_CONTRACT,
    build_stop_recommendation_artifact,
)
from trading_execution_engine.simulation.persistent_account import (
    initialize_persistent_account,
)


NOW = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)


def _handoff() -> OptimizerTargetHandoff:
    rows = (
        OptimizerTargetRow(
            symbol="AAA",
            share_delta=20,
            trade_side="BUY",
            current_position=40,
            target_shares=60,
            reference_price=100.0,
            approved_target_weight=0.60,
            execution_state="PAPER",
        ),
        OptimizerTargetRow(
            symbol="BBB",
            share_delta=-5,
            trade_side="SELL",
            current_position=25,
            target_shares=20,
            reference_price=200.0,
            approved_target_weight=0.40,
            execution_state="PAPER",
        ),
        OptimizerTargetRow(
            symbol="CCC",
            share_delta=-5,
            trade_side="SELL",
            current_position=5,
            target_shares=0,
            reference_price=50.0,
            approved_target_weight=0.0,
            execution_state="PAPER",
        ),
    )
    return OptimizerTargetHandoff(
        target_path=Path("targets.csv"),
        manifest_path=Path("manifest.json"),
        artifact_sha256="a" * 64,
        contract_version="portfolio-target-handoff-v1",
        target_builder_version="1.2.0",
        as_of_session="2026-10-21",
        allocation_contract_version="scanner-candidate-allocation-v1",
        allocation_sha256="b" * 64,
        allocation_manifest_sha256="c" * 64,
        scanner_snapshot_sha256="d" * 64,
        positions_sha256="e" * 64,
        portfolio_capital=10000.0,
        execution_state="PAPER",
        rows=rows,
    )


def _state():
    return initialize_persistent_account(
        cash=750.0,
        positions={
            "AAA": 40,
            "BBB": 25,
            "CCC": 5,
        },
        updated_at_utc=NOW,
    )


def test_stop_recommendation_export_is_review_only_and_deterministic(
    tmp_path,
):
    artifact = build_stop_recommendation_artifact(
        handoff=_handoff(),
        state=_state(),
        policy=StopPolicy(
            stop_type=ProtectiveStopType.STOP_LIMIT,
            stop_distance_pct=8.0,
            stop_limit_buffer_bps=50.0,
        ),
        output_dir=tmp_path / "stops",
        generated_at_utc=NOW,
    )

    assert artifact.row_count == 2

    with artifact.csv_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert [row["symbol"] for row in rows] == ["AAA", "BBB"]
    assert rows[0]["quantity"] == "60"
    assert rows[0]["reference_price"] == "100.0"
    assert rows[0]["stop_price"] == "92.0"
    assert rows[0]["stop_limit_price"] == "91.54"
    assert rows[0]["review_only"] == "True"
    assert rows[0]["broker_submission_permitted"] == "False"

    manifest = json.loads(
        artifact.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["contract_version"] == STOP_RECOMMENDATION_CONTRACT
    assert manifest["paper_state_sha256"] == _state().state_sha256
    assert manifest["optimizer_artifact_sha256"] == "a" * 64
    assert manifest["quantity_basis"] == "optimizer_target_shares"
    assert manifest["immutable"] is True
    assert manifest["review_only"] is True
    assert manifest["broker_submission_permitted"] is False
    assert (
        manifest["protective_stop_recommendations_sha256"]
        == artifact.csv_sha256
    )


def test_stop_export_excludes_zero_target_positions(tmp_path):
    artifact = build_stop_recommendation_artifact(
        handoff=_handoff(),
        state=_state(),
        policy=StopPolicy(),
        output_dir=tmp_path / "stops",
        generated_at_utc=NOW,
    )

    symbols = artifact.csv_path.read_text(encoding="utf-8")
    assert "AAA" in symbols
    assert "BBB" in symbols
    assert "CCC" not in symbols


def test_stop_export_requires_state_handoff_position_match(tmp_path):
    mismatched = initialize_persistent_account(
        cash=750.0,
        positions={
            "AAA": 39,
            "BBB": 25,
            "CCC": 5,
        },
        updated_at_utc=NOW,
    )

    with pytest.raises(ValueError, match="do not match"):
        build_stop_recommendation_artifact(
            handoff=_handoff(),
            state=mismatched,
            policy=StopPolicy(),
            output_dir=tmp_path / "stops",
            generated_at_utc=NOW,
        )


def test_stop_export_is_immutable(tmp_path):
    destination = tmp_path / "stops"
    build_stop_recommendation_artifact(
        handoff=_handoff(),
        state=_state(),
        policy=StopPolicy(),
        output_dir=destination,
        generated_at_utc=NOW,
    )

    with pytest.raises(FileExistsError, match="already exists"):
        build_stop_recommendation_artifact(
            handoff=_handoff(),
            state=_state(),
            policy=StopPolicy(),
            output_dir=destination,
            generated_at_utc=NOW,
        )
