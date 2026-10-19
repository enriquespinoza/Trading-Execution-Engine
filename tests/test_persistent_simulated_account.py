from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from trading_execution_engine.models.account import AccountState
from trading_execution_engine.simulation.persistent_account import (
    advance_persistent_account,
    initialize_persistent_account,
    load_persistent_account,
    save_persistent_account,
)


NOW = datetime(
    2026, 10, 19, 15, 0, tzinfo=timezone.utc
)


def test_initialize_save_and_load_round_trip(tmp_path):
    state = initialize_persistent_account(
        cash=100000.0,
        positions={},
        updated_at_utc=NOW,
    )
    path = tmp_path / "paper_account.json"
    save_persistent_account(state, path)

    loaded = load_persistent_account(path)

    assert loaded == state
    assert loaded.state_version == 1
    assert loaded.previous_state_sha256 is None


def test_advanced_state_links_to_previous_hash():
    first = initialize_persistent_account(
        cash=100000.0,
        positions={},
        updated_at_utc=NOW,
    )
    account = AccountState(
        cash=95000.0,
        positions={"AAA": 50},
    )

    second = advance_persistent_account(
        previous=first,
        account=account,
        source_artifact_sha256="a" * 64,
        market_snapshot_sha256="b" * 64,
        order_ids=("order-1",),
        updated_at_utc=NOW,
    )

    assert second.state_version == 2
    assert second.previous_state_sha256 == first.state_sha256
    assert second.cash == 95000.0
    assert second.positions == {"AAA": 50.0}


def test_tampered_state_rejected(tmp_path):
    state = initialize_persistent_account(
        cash=100000.0,
        updated_at_utc=NOW,
    )
    path = tmp_path / "paper_account.json"
    save_persistent_account(state, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cash"] = 99999.0
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SHA-256"):
        load_persistent_account(path)


def test_fractional_positions_rejected():
    with pytest.raises(ValueError, match="fractional"):
        initialize_persistent_account(
            cash=100000.0,
            positions={"AAA": 1.5},
            updated_at_utc=NOW,
        )
