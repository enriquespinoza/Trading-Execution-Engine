from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

from trading_execution_engine.engine import ExecutionResult
from trading_execution_engine.integrations.optimizer_targets import (
    PORTFOLIO_TARGET_HANDOFF_VERSION,
    TARGET_COLUMNS,
)
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from trading_execution_engine.risk.limits import RiskDecision
from trading_execution_engine.simulation.persistent_account import (
    initialize_persistent_account,
    load_persistent_account,
    save_persistent_account,
)
from trading_execution_engine.simulation.working_orders import (
    build_working_order_store,
    load_working_order_store,
    save_working_order_store,
)


CAPTURED = datetime(
    2026,
    10,
    21,
    15,
    0,
    tzinfo=timezone.utc,
)


def _runner_module() -> ModuleType:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_market_data_paper_simulation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "phase2k_market_data_paper_runner",
        script,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows() -> list[dict[str, str]]:
    common = {
        "handoff_contract_version": PORTFOLIO_TARGET_HANDOFF_VERSION,
        "target_builder_version": "1.2.0",
        "as_of_session": "2026-10-21",
        "allocation_contract_version": "scanner-candidate-allocation-v1",
        "allocation_sha256": "a" * 64,
        "allocation_manifest_sha256": "b" * 64,
        "scanner_snapshot_sha256": "c" * 64,
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


def _write_bundle(tmp_path: Path) -> tuple[Path, Path, str]:
    targets = tmp_path / "execution_safe_targets.csv"
    manifest = tmp_path / "manifest.json"

    with targets.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows(_rows())

    artifact_sha = _sha256(targets)
    payload = {
        "handoff_contract_version": PORTFOLIO_TARGET_HANDOFF_VERSION,
        "target_builder_version": "1.2.0",
        "as_of_session": "2026-10-21",
        "allocation_contract_version": "scanner-candidate-allocation-v1",
        "allocation_sha256": "a" * 64,
        "allocation_manifest_sha256": "b" * 64,
        "scanner_snapshot_sha256": "c" * 64,
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
        "generated_at_utc": "2026-10-21T20:00:00+00:00",
        "immutable": True,
        "broker_submission_permitted": False,
        "positions_sha256": "d" * 64,
        "execution_safe_targets_sha256": artifact_sha,
    }
    manifest.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return targets, manifest, artifact_sha


def _write_market_capture(
    path: Path,
    *,
    bbb_price: float,
) -> None:
    quote_time = int(
        datetime(
            2026,
            10,
            21,
            14,
            59,
            tzinfo=timezone.utc,
        ).timestamp()
        * 1000
    )
    prices = {
        "AAA": 100.0,
        "BBB": float(bbb_price),
        "CCC": 50.0,
    }
    payload = {
        "capture_contract": "schwab-market-data-capture-v1",
        "captured_at_utc": CAPTURED.isoformat(),
        "symbols": ["AAA", "BBB", "CCC"],
        "quotes": {
            symbol: {
                "quote": {
                    "lastPrice": price,
                    "quoteTime": quote_time,
                }
            }
            for symbol, price in prices.items()
        },
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_initial_state(path: Path):
    state = initialize_persistent_account(
        cash=750.0,
        positions={
            "AAA": 40,
            "BBB": 25,
            "CCC": 5,
        },
        updated_at_utc=CAPTURED,
    )
    save_persistent_account(state, path)
    return state


def _runner_argv(
    *,
    targets: Path,
    manifest: Path,
    artifact_sha: str,
    capture: Path,
    state: Path,
    working: Path,
) -> list[str]:
    return [
        "run_market_data_paper_simulation.py",
        "--targets",
        str(targets),
        "--manifest",
        str(manifest),
        "--expected-sha256",
        artifact_sha,
        "--market-capture",
        str(capture),
        "--state",
        str(state),
        "--working-orders-state",
        str(working),
        "--use-limit-orders",
        "--buy-limit-tolerance-bps",
        "0",
        "--sell-limit-tolerance-bps",
        "100",
    ]


def _run(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    argv: list[str],
) -> None:
    monkeypatch.setattr(sys, "argv", argv)
    module.main()


def _setup_runner_case(tmp_path: Path):
    targets, manifest, artifact_sha = _write_bundle(tmp_path)
    capture = tmp_path / "market_capture.json"
    state_path = tmp_path / "paper_account.json"
    working_path = tmp_path / "working_orders.json"
    state = _write_initial_state(state_path)

    return {
        "targets": targets,
        "manifest": manifest,
        "artifact_sha": artifact_sha,
        "capture": capture,
        "state_path": state_path,
        "working_path": working_path,
        "state": state,
    }


def test_runner_creates_working_store_without_advancing_account(
    tmp_path,
    monkeypatch,
):
    case = _setup_runner_case(tmp_path)
    _write_market_capture(case["capture"], bbb_price=197.0)

    before = case["state_path"].read_bytes()
    module = _runner_module()
    _run(
        monkeypatch,
        module,
        _runner_argv(
            targets=case["targets"],
            manifest=case["manifest"],
            artifact_sha=case["artifact_sha"],
            capture=case["capture"],
            state=case["state_path"],
            working=case["working_path"],
        ),
    )

    assert case["state_path"].read_bytes() == before

    account = load_persistent_account(case["state_path"])
    assert account.state_version == 1
    assert account.state_sha256 == case["state"].state_sha256

    working = load_working_order_store(case["working_path"])
    assert working.store_version == 1
    assert working.account_state_sha256 == account.state_sha256
    assert working.source_artifact_sha256 == case["artifact_sha"]
    assert len(working.orders) == 1
    assert working.orders[0].symbol == "BBB"
    assert working.orders[0].status == OrderStatus.WORKING


def test_runner_retries_working_store_without_advancing_account(
    tmp_path,
    monkeypatch,
):
    case = _setup_runner_case(tmp_path)
    _write_market_capture(case["capture"], bbb_price=197.0)

    module = _runner_module()
    argv = _runner_argv(
        targets=case["targets"],
        manifest=case["manifest"],
        artifact_sha=case["artifact_sha"],
        capture=case["capture"],
        state=case["state_path"],
        working=case["working_path"],
    )

    _run(monkeypatch, module, argv)
    first = load_working_order_store(case["working_path"])
    account_before = case["state_path"].read_bytes()

    _run(monkeypatch, module, argv)
    second = load_working_order_store(case["working_path"])

    assert case["state_path"].read_bytes() == account_before
    assert second.store_version == 2
    assert second.previous_store_sha256 == first.store_sha256
    assert second.account_state_sha256 == case["state"].state_sha256
    assert second.source_artifact_sha256 == case["artifact_sha"]


def test_runner_crossed_limits_advance_account_and_remove_working_store(
    tmp_path,
    monkeypatch,
):
    case = _setup_runner_case(tmp_path)
    module = _runner_module()
    argv = _runner_argv(
        targets=case["targets"],
        manifest=case["manifest"],
        artifact_sha=case["artifact_sha"],
        capture=case["capture"],
        state=case["state_path"],
        working=case["working_path"],
    )

    _write_market_capture(case["capture"], bbb_price=197.0)
    _run(monkeypatch, module, argv)

    working = load_working_order_store(case["working_path"])
    assert working.store_version == 1
    assert (
        load_persistent_account(case["state_path"]).state_version
        == 1
    )

    _write_market_capture(case["capture"], bbb_price=200.0)
    _run(monkeypatch, module, argv)

    advanced = load_persistent_account(case["state_path"])
    assert advanced.state_version == 2
    assert advanced.previous_state_sha256 == case["state"].state_sha256
    assert advanced.source_artifact_sha256 == case["artifact_sha"]
    assert advanced.positions == {
        "AAA": 60.0,
        "BBB": 20.0,
    }
    assert advanced.cash == 0.0
    assert not case["working_path"].exists()


def test_runner_fails_closed_for_working_store_state_or_artifact_mismatch(
    tmp_path,
    monkeypatch,
):
    targets, manifest, artifact_sha = _write_bundle(tmp_path)
    capture = tmp_path / "market_capture.json"
    _write_market_capture(capture, bbb_price=197.0)
    module = _runner_module()

    for mismatch in ("state", "artifact"):
        case_dir = tmp_path / mismatch
        case_dir.mkdir()

        state_path = case_dir / "paper_account.json"
        working_path = case_dir / "working_orders.json"
        state = _write_initial_state(state_path)

        order = OrderRequest(
            symbol="BBB",
            side=OrderSide.SELL,
            quantity=5,
            order_type=OrderType.LIMIT,
            limit_price=198.0,
            order_id=f"working-{mismatch}",
        )
        result = ExecutionResult(
            order=order,
            risk=RiskDecision(True, "approved"),
            fill=None,
            cash_after=state.cash,
            status=OrderStatus.WORKING,
            execution_reason="limit_not_marketable",
        )

        store = build_working_order_store(
            account_state_sha256=(
                "f" * 64
                if mismatch == "state"
                else state.state_sha256
            ),
            source_artifact_sha256=(
                "f" * 64
                if mismatch == "artifact"
                else artifact_sha
            ),
            market_snapshot_sha256="e" * 64,
            results=[result],
            updated_at_utc=CAPTURED,
        )
        save_working_order_store(store, working_path)

        argv = _runner_argv(
            targets=targets,
            manifest=manifest,
            artifact_sha=artifact_sha,
            capture=capture,
            state=state_path,
            working=working_path,
        )

        expected = (
            "different persistent paper-account state"
            if mismatch == "state"
            else "different optimizer artifact"
        )
        with pytest.raises(SystemExit, match=expected):
            _run(monkeypatch, module, argv)

        unchanged = load_persistent_account(state_path)
        assert unchanged.state_sha256 == state.state_sha256
        assert working_path.exists()
