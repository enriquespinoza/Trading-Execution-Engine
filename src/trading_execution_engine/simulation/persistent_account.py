from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from trading_execution_engine.models.account import AccountState


PERSISTENT_ACCOUNT_CONTRACT = "persistent-simulation-account-v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_positions(
    positions: Mapping[str, float],
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for raw_symbol, raw_quantity in positions.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            raise ValueError("position symbol cannot be empty")
        try:
            quantity = float(raw_quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"position quantity must be numeric: {symbol}"
            ) from exc
        if not math.isfinite(quantity):
            raise ValueError(
                f"position quantity must be finite: {symbol}"
            )
        if quantity < 0:
            raise ValueError(
                f"short positions are not supported: {symbol}"
            )
        if not quantity.is_integer():
            raise ValueError(
                f"fractional positions are not supported: {symbol}"
            )
        if quantity:
            normalized[symbol] = quantity
    return dict(sorted(normalized.items()))


def _canonical_payload(
    *,
    state_version: int,
    updated_at_utc: datetime,
    cash: float,
    positions: Mapping[str, float],
    previous_state_sha256: str | None,
    source_artifact_sha256: str | None,
    market_snapshot_sha256: str | None,
    last_order_ids: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "contract_version": PERSISTENT_ACCOUNT_CONTRACT,
        "state_version": state_version,
        "updated_at_utc": updated_at_utc.astimezone(
            timezone.utc
        ).isoformat(),
        "cash": cash,
        "positions": dict(sorted(positions.items())),
        "previous_state_sha256": previous_state_sha256,
        "source_artifact_sha256": source_artifact_sha256,
        "market_snapshot_sha256": market_snapshot_sha256,
        "last_order_ids": list(last_order_ids),
    }


def _state_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class PersistentSimulationAccount:
    state_version: int
    updated_at_utc: datetime
    cash: float
    positions: dict[str, float]
    previous_state_sha256: str | None
    source_artifact_sha256: str | None
    market_snapshot_sha256: str | None
    last_order_ids: tuple[str, ...]
    state_sha256: str

    def __post_init__(self) -> None:
        if self.state_version < 1:
            raise ValueError("state_version must be positive")
        if self.updated_at_utc.tzinfo is None:
            raise ValueError("updated_at_utc must be timezone-aware")
        if not math.isfinite(self.cash) or self.cash < 0:
            raise ValueError("cash must be finite and non-negative")
        _normalize_positions(self.positions)
        if len(self.state_sha256) != 64:
            raise ValueError("state_sha256 must be a SHA-256 digest")

    def to_account_state(self) -> AccountState:
        return AccountState.from_mapping(
            cash=self.cash,
            positions=self.positions,
        )

    def to_json_dict(self) -> dict[str, Any]:
        payload = _canonical_payload(
            state_version=self.state_version,
            updated_at_utc=self.updated_at_utc,
            cash=self.cash,
            positions=self.positions,
            previous_state_sha256=self.previous_state_sha256,
            source_artifact_sha256=self.source_artifact_sha256,
            market_snapshot_sha256=self.market_snapshot_sha256,
            last_order_ids=self.last_order_ids,
        )
        payload["state_sha256"] = self.state_sha256
        return payload


def _build_state(
    *,
    state_version: int,
    updated_at_utc: datetime,
    cash: float,
    positions: Mapping[str, float],
    previous_state_sha256: str | None,
    source_artifact_sha256: str | None,
    market_snapshot_sha256: str | None,
    last_order_ids: tuple[str, ...],
) -> PersistentSimulationAccount:
    if not math.isfinite(float(cash)) or float(cash) < 0:
        raise ValueError("cash must be finite and non-negative")

    normalized_positions = _normalize_positions(positions)
    updated = updated_at_utc.astimezone(timezone.utc)
    payload = _canonical_payload(
        state_version=state_version,
        updated_at_utc=updated,
        cash=float(cash),
        positions=normalized_positions,
        previous_state_sha256=previous_state_sha256,
        source_artifact_sha256=source_artifact_sha256,
        market_snapshot_sha256=market_snapshot_sha256,
        last_order_ids=tuple(last_order_ids),
    )
    digest = _state_sha256(payload)

    return PersistentSimulationAccount(
        state_version=state_version,
        updated_at_utc=updated,
        cash=float(cash),
        positions=normalized_positions,
        previous_state_sha256=previous_state_sha256,
        source_artifact_sha256=source_artifact_sha256,
        market_snapshot_sha256=market_snapshot_sha256,
        last_order_ids=tuple(last_order_ids),
        state_sha256=digest,
    )


def initialize_persistent_account(
    *,
    cash: float,
    positions: Mapping[str, float] | None = None,
    updated_at_utc: datetime | None = None,
) -> PersistentSimulationAccount:
    return _build_state(
        state_version=1,
        updated_at_utc=updated_at_utc or _utc_now(),
        cash=cash,
        positions=positions or {},
        previous_state_sha256=None,
        source_artifact_sha256=None,
        market_snapshot_sha256=None,
        last_order_ids=(),
    )


def advance_persistent_account(
    *,
    previous: PersistentSimulationAccount,
    account: AccountState,
    source_artifact_sha256: str,
    market_snapshot_sha256: str,
    order_ids: tuple[str, ...],
    updated_at_utc: datetime | None = None,
) -> PersistentSimulationAccount:
    return _build_state(
        state_version=previous.state_version + 1,
        updated_at_utc=updated_at_utc or _utc_now(),
        cash=account.cash,
        positions=account.positions,
        previous_state_sha256=previous.state_sha256,
        source_artifact_sha256=source_artifact_sha256,
        market_snapshot_sha256=market_snapshot_sha256,
        last_order_ids=order_ids,
    )


def save_persistent_account(
    state: PersistentSimulationAccount,
    path: str | Path,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    encoded = (
        json.dumps(
            state.to_json_dict(),
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


def load_persistent_account(
    path: str | Path,
) -> PersistentSimulationAccount:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(
            f"persistent simulation state not found: {source}"
        )

    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("persistent simulation state must be an object")

    if payload.get("contract_version") != PERSISTENT_ACCOUNT_CONTRACT:
        raise ValueError("unsupported persistent simulation account contract")

    updated = datetime.fromisoformat(
        str(payload["updated_at_utc"]).replace("Z", "+00:00")
    )
    if updated.tzinfo is None:
        raise ValueError("updated_at_utc must be timezone-aware")

    expected_sha = str(payload.get("state_sha256", "")).strip()
    unsigned = _canonical_payload(
        state_version=int(payload["state_version"]),
        updated_at_utc=updated,
        cash=float(payload["cash"]),
        positions=_normalize_positions(payload.get("positions", {})),
        previous_state_sha256=payload.get("previous_state_sha256"),
        source_artifact_sha256=payload.get("source_artifact_sha256"),
        market_snapshot_sha256=payload.get("market_snapshot_sha256"),
        last_order_ids=tuple(payload.get("last_order_ids", [])),
    )
    actual_sha = _state_sha256(unsigned)
    if expected_sha != actual_sha:
        raise ValueError(
            "persistent simulation state SHA-256 verification failed"
        )

    return PersistentSimulationAccount(
        state_version=int(payload["state_version"]),
        updated_at_utc=updated.astimezone(timezone.utc),
        cash=float(payload["cash"]),
        positions=_normalize_positions(payload.get("positions", {})),
        previous_state_sha256=payload.get("previous_state_sha256"),
        source_artifact_sha256=payload.get("source_artifact_sha256"),
        market_snapshot_sha256=payload.get("market_snapshot_sha256"),
        last_order_ids=tuple(payload.get("last_order_ids", [])),
        state_sha256=actual_sha,
    )
