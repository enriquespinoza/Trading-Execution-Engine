from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from trading_execution_engine.engine import ExecutionResult
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from trading_execution_engine.risk.limits import RiskDecision
from trading_execution_engine.simulation.working_orders import (
    WORKING_ORDER_STORE_CONTRACT,
    build_working_order_store,
    load_working_order_store,
    save_working_order_store,
)


NOW = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)


def working_result(
    *,
    order_id: str = "order-1",
    symbol: str = "AAA",
    side: OrderSide = OrderSide.BUY,
    limit_price: float = 99.0,
) -> ExecutionResult:
    order = OrderRequest(
        symbol=symbol,
        side=side,
        quantity=5,
        order_type=OrderType.LIMIT,
        limit_price=limit_price,
        order_id=order_id,
    )
    return ExecutionResult(
        order=order,
        risk=RiskDecision(True, "approved"),
        fill=None,
        cash_after=1000.0,
        status=OrderStatus.WORKING,
        execution_reason="limit_not_marketable",
    )


def test_working_order_store_round_trip(tmp_path):
    store = build_working_order_store(
        account_state_sha256="a" * 64,
        source_artifact_sha256="b" * 64,
        market_snapshot_sha256="c" * 64,
        results=[working_result()],
        updated_at_utc=NOW,
    )

    path = tmp_path / "working_orders.json"
    save_working_order_store(store, path)
    loaded = load_working_order_store(path)

    assert loaded.store_version == 1
    assert loaded.account_state_sha256 == "a" * 64
    assert loaded.source_artifact_sha256 == "b" * 64
    assert loaded.market_snapshot_sha256 == "c" * 64
    assert loaded.previous_store_sha256 is None
    assert loaded.orders == store.orders
    assert loaded.store_sha256 == store.store_sha256
    assert loaded.to_json_dict()["contract_version"] == (
        WORKING_ORDER_STORE_CONTRACT
    )


def test_working_order_store_update_is_hash_chained():
    first = build_working_order_store(
        account_state_sha256="a" * 64,
        source_artifact_sha256="b" * 64,
        market_snapshot_sha256="c" * 64,
        results=[working_result()],
        updated_at_utc=NOW,
    )

    second = build_working_order_store(
        account_state_sha256="a" * 64,
        source_artifact_sha256="b" * 64,
        market_snapshot_sha256="d" * 64,
        results=[working_result()],
        previous=first,
        updated_at_utc=NOW,
    )

    assert second.store_version == 2
    assert second.previous_store_sha256 == first.store_sha256
    assert second.store_sha256 != first.store_sha256


def test_working_order_store_rejects_different_base_state():
    first = build_working_order_store(
        account_state_sha256="a" * 64,
        source_artifact_sha256="b" * 64,
        market_snapshot_sha256="c" * 64,
        results=[working_result()],
        updated_at_utc=NOW,
    )

    with pytest.raises(ValueError, match="account state"):
        build_working_order_store(
            account_state_sha256="f" * 64,
            source_artifact_sha256="b" * 64,
            market_snapshot_sha256="d" * 64,
            results=[working_result()],
            previous=first,
            updated_at_utc=NOW,
        )


def test_working_order_store_tamper_fails_hash_check(tmp_path):
    store = build_working_order_store(
        account_state_sha256="a" * 64,
        source_artifact_sha256="b" * 64,
        market_snapshot_sha256="c" * 64,
        results=[working_result()],
        updated_at_utc=NOW,
    )

    path = tmp_path / "working_orders.json"
    save_working_order_store(store, path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["orders"][0]["limit_price"] = 1.0
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SHA-256 verification failed"):
        load_working_order_store(path)
