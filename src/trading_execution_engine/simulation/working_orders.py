from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from trading_execution_engine.engine import ExecutionResult
from trading_execution_engine.models.order import (
    OrderSide,
    OrderStatus,
    OrderType,
)


WORKING_ORDER_STORE_CONTRACT = "working-order-store-v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_sha256(value: str, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if (
        len(normalized) != 64
        or any(ch not in "0123456789abcdef" for ch in normalized)
    ):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return normalized


@dataclass(frozen=True)
class WorkingOrderRecord:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    limit_price: float
    status: OrderStatus = OrderStatus.WORKING

    def __post_init__(self) -> None:
        if not self.order_id.strip():
            raise ValueError("working order_id is required")
        if not self.symbol.strip():
            raise ValueError("working order symbol is required")
        if not math.isfinite(float(self.quantity)) or self.quantity <= 0:
            raise ValueError("working order quantity must be positive")
        if not float(self.quantity).is_integer():
            raise ValueError("working order quantity must be whole shares")
        if self.order_type != OrderType.LIMIT:
            raise ValueError("working-order store only supports LIMIT orders")
        if not math.isfinite(float(self.limit_price)) or self.limit_price <= 0:
            raise ValueError("working order limit_price must be positive")
        if self.status != OrderStatus.WORKING:
            raise ValueError("working-order record status must be WORKING")


@dataclass(frozen=True)
class WorkingOrderStore:
    store_version: int
    updated_at_utc: datetime
    account_state_sha256: str
    source_artifact_sha256: str
    market_snapshot_sha256: str
    previous_store_sha256: str | None
    orders: tuple[WorkingOrderRecord, ...]
    store_sha256: str

    def __post_init__(self) -> None:
        if self.store_version < 1:
            raise ValueError("store_version must be positive")
        if self.updated_at_utc.tzinfo is None:
            raise ValueError("updated_at_utc must be timezone-aware")
        _require_sha256(
            self.account_state_sha256,
            field="account_state_sha256",
        )
        _require_sha256(
            self.source_artifact_sha256,
            field="source_artifact_sha256",
        )
        _require_sha256(
            self.market_snapshot_sha256,
            field="market_snapshot_sha256",
        )
        if self.previous_store_sha256 is not None:
            _require_sha256(
                self.previous_store_sha256,
                field="previous_store_sha256",
            )
        _require_sha256(self.store_sha256, field="store_sha256")
        if not self.orders:
            raise ValueError("working-order store cannot be empty")

        ids = [order.order_id for order in self.orders]
        if len(ids) != len(set(ids)):
            raise ValueError("working-order IDs must be unique")

    def to_json_dict(self) -> dict[str, Any]:
        payload = _canonical_payload(
            store_version=self.store_version,
            updated_at_utc=self.updated_at_utc,
            account_state_sha256=self.account_state_sha256,
            source_artifact_sha256=self.source_artifact_sha256,
            market_snapshot_sha256=self.market_snapshot_sha256,
            previous_store_sha256=self.previous_store_sha256,
            orders=self.orders,
        )
        payload["store_sha256"] = self.store_sha256
        return payload


def _order_payload(order: WorkingOrderRecord) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "symbol": order.symbol.upper(),
        "side": order.side.value,
        "quantity": float(order.quantity),
        "order_type": order.order_type.value,
        "limit_price": float(order.limit_price),
        "status": order.status.value,
    }


def _canonical_payload(
    *,
    store_version: int,
    updated_at_utc: datetime,
    account_state_sha256: str,
    source_artifact_sha256: str,
    market_snapshot_sha256: str,
    previous_store_sha256: str | None,
    orders: tuple[WorkingOrderRecord, ...],
) -> dict[str, Any]:
    return {
        "contract_version": WORKING_ORDER_STORE_CONTRACT,
        "store_version": int(store_version),
        "updated_at_utc": updated_at_utc.astimezone(
            timezone.utc
        ).isoformat(),
        "account_state_sha256": _require_sha256(
            account_state_sha256,
            field="account_state_sha256",
        ),
        "source_artifact_sha256": _require_sha256(
            source_artifact_sha256,
            field="source_artifact_sha256",
        ),
        "market_snapshot_sha256": _require_sha256(
            market_snapshot_sha256,
            field="market_snapshot_sha256",
        ),
        "previous_store_sha256": (
            _require_sha256(
                previous_store_sha256,
                field="previous_store_sha256",
            )
            if previous_store_sha256 is not None
            else None
        ),
        "orders": [
            _order_payload(order)
            for order in sorted(orders, key=lambda value: value.order_id)
        ],
    }


def _store_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_working_order_store(
    *,
    account_state_sha256: str,
    source_artifact_sha256: str,
    market_snapshot_sha256: str,
    results: Iterable[ExecutionResult],
    previous: WorkingOrderStore | None = None,
    updated_at_utc: datetime | None = None,
) -> WorkingOrderStore:
    records: list[WorkingOrderRecord] = []

    for result in results:
        if result.status != OrderStatus.WORKING:
            continue
        order = result.order
        if order.order_type != OrderType.LIMIT:
            raise ValueError("WORKING result must contain a LIMIT order")
        if order.limit_price is None:
            raise ValueError("WORKING LIMIT order requires limit_price")

        records.append(
            WorkingOrderRecord(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                order_type=order.order_type,
                limit_price=order.limit_price,
            )
        )

    if not records:
        raise ValueError("no WORKING orders supplied")

    account_sha = _require_sha256(
        account_state_sha256,
        field="account_state_sha256",
    )
    artifact_sha = _require_sha256(
        source_artifact_sha256,
        field="source_artifact_sha256",
    )

    version = 1
    previous_sha: str | None = None

    if previous is not None:
        if previous.account_state_sha256 != account_sha:
            raise ValueError(
                "working-order store account state does not match current state"
            )
        if previous.source_artifact_sha256 != artifact_sha:
            raise ValueError(
                "working-order store optimizer artifact does not match"
            )
        version = previous.store_version + 1
        previous_sha = previous.store_sha256

    updated = (updated_at_utc or _utc_now()).astimezone(timezone.utc)
    order_tuple = tuple(sorted(records, key=lambda value: value.order_id))

    payload = _canonical_payload(
        store_version=version,
        updated_at_utc=updated,
        account_state_sha256=account_sha,
        source_artifact_sha256=artifact_sha,
        market_snapshot_sha256=market_snapshot_sha256,
        previous_store_sha256=previous_sha,
        orders=order_tuple,
    )
    digest = _store_sha256(payload)

    return WorkingOrderStore(
        store_version=version,
        updated_at_utc=updated,
        account_state_sha256=account_sha,
        source_artifact_sha256=artifact_sha,
        market_snapshot_sha256=_require_sha256(
            market_snapshot_sha256,
            field="market_snapshot_sha256",
        ),
        previous_store_sha256=previous_sha,
        orders=order_tuple,
        store_sha256=digest,
    )


def save_working_order_store(
    store: WorkingOrderStore,
    path: str | Path,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    encoded = (
        json.dumps(
            store.to_json_dict(),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def load_working_order_store(
    path: str | Path,
) -> WorkingOrderStore:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"working-order state not found: {source}"
        )

    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("working-order state must be an object")
    if payload.get("contract_version") != WORKING_ORDER_STORE_CONTRACT:
        raise ValueError("unsupported working-order store contract")

    updated = datetime.fromisoformat(
        str(payload["updated_at_utc"]).replace("Z", "+00:00")
    )
    if updated.tzinfo is None:
        raise ValueError("updated_at_utc must be timezone-aware")

    raw_orders = payload.get("orders")
    if not isinstance(raw_orders, list) or not raw_orders:
        raise ValueError("working-order state must contain orders")

    orders = tuple(
        WorkingOrderRecord(
            order_id=str(item["order_id"]),
            symbol=str(item["symbol"]),
            side=OrderSide(str(item["side"])),
            quantity=float(item["quantity"]),
            order_type=OrderType(str(item["order_type"])),
            limit_price=float(item["limit_price"]),
            status=OrderStatus(str(item["status"])),
        )
        for item in raw_orders
    )

    canonical = _canonical_payload(
        store_version=int(payload["store_version"]),
        updated_at_utc=updated,
        account_state_sha256=str(payload["account_state_sha256"]),
        source_artifact_sha256=str(payload["source_artifact_sha256"]),
        market_snapshot_sha256=str(payload["market_snapshot_sha256"]),
        previous_store_sha256=payload.get("previous_store_sha256"),
        orders=orders,
    )

    expected_sha = str(payload.get("store_sha256", "")).strip().lower()
    actual_sha = _store_sha256(canonical)
    if expected_sha != actual_sha:
        raise ValueError(
            "working-order store SHA-256 verification failed"
        )

    return WorkingOrderStore(
        store_version=int(payload["store_version"]),
        updated_at_utc=updated.astimezone(timezone.utc),
        account_state_sha256=canonical["account_state_sha256"],
        source_artifact_sha256=canonical["source_artifact_sha256"],
        market_snapshot_sha256=canonical["market_snapshot_sha256"],
        previous_store_sha256=canonical["previous_store_sha256"],
        orders=orders,
        store_sha256=actual_sha,
    )
