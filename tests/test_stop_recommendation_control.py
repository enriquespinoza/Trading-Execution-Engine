from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _control_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_stop_recommendation_control.py"
    )
    spec = importlib.util.spec_from_file_location(
        "stop_recommendation_control",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_control_stop_recommendation_artifact(tmp_path):
    module = _control_module()
    result = module.generate_control_case(tmp_path / "control")

    assert result["row_count"] == 2
    assert [row["symbol"] for row in result["rows"]] == ["AAA", "BBB"]

    assert (
        result["manifest"]["protective_stop_recommendations_sha256"]
        == result["recommendation_csv_sha256"]
    )
    assert (
        result["manifest"]["optimizer_artifact_sha256"]
        == result["optimizer_artifact_sha256"]
    )
    assert (
        result["manifest"]["paper_state_sha256"]
        == result["paper_state_sha256"]
    )
    assert result["manifest"]["paper_state_version"] == 3
    assert result["manifest"]["review_only"] is True
    assert result["manifest"]["broker_submission_permitted"] is False

    by_symbol = {row["symbol"]: row for row in result["rows"]}
    assert by_symbol["AAA"]["stop_price"] == "92.0"
    assert by_symbol["AAA"]["stop_limit_price"] == "91.54"
    assert by_symbol["BBB"]["stop_price"] == "184.0"
    assert by_symbol["BBB"]["stop_limit_price"] == "183.08"
