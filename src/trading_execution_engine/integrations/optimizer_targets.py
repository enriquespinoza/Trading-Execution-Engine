from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderType,
)


PORTFOLIO_TARGET_HANDOFF_VERSION = "portfolio-target-handoff-v1"
ALLOWED_EXECUTION_STATES = frozenset({"DRY_RUN", "PAPER"})
ALLOWED_TARGET_STATUSES = frozenset(
    {"TARGETED", "ZERO_WEIGHT", "ROUNDING_TO_ZERO", "EXIT"}
)
ALLOWED_TRADE_SIDES = frozenset({"BUY", "SELL", "HOLD"})
ALLOWED_REFERENCE_PRICE_SOURCES = frozenset(
    {"scanner_allocation_close", "position_snapshot"}
)

TARGET_COLUMNS = (
    "handoff_contract_version",
    "target_builder_version",
    "as_of_session",
    "allocation_contract_version",
    "allocation_sha256",
    "allocation_manifest_sha256",
    "scanner_snapshot_sha256",
    "symbol",
    "scanner_rank",
    "approved_target_weight",
    "reference_price",
    "reference_price_source",
    "portfolio_capital",
    "target_dollar_value",
    "target_shares",
    "target_share_notional",
    "realized_target_weight",
    "weight_rounding_error",
    "target_status",
    "current_position",
    "share_delta",
    "trade_side",
    "execution_state",
)

_REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "handoff_contract_version",
        "target_builder_version",
        "as_of_session",
        "allocation_contract_version",
        "allocation_sha256",
        "allocation_manifest_sha256",
        "scanner_snapshot_sha256",
        "portfolio_capital",
        "execution_state",
        "share_rounding_policy",
        "row_count",
        "target_symbol_count",
        "targeted_count",
        "zero_weight_count",
        "rounding_to_zero_count",
        "exit_count",
        "buy_count",
        "sell_count",
        "hold_count",
        "target_notional",
        "residual_cash",
        "realized_weight_sum",
        "total_weight_rounding_error",
        "generated_at_utc",
        "immutable",
        "broker_submission_permitted",
        "positions_sha256",
        "execution_safe_targets_sha256",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_FLOAT_ABS_TOL = 1e-8


@dataclass(frozen=True)
class OptimizerTargetRow:
    symbol: str
    share_delta: int
    trade_side: str
    current_position: int
    target_shares: int
    reference_price: float
    approved_target_weight: float
    execution_state: str


@dataclass(frozen=True)
class OptimizerTargetHandoff:
    target_path: Path
    manifest_path: Path
    artifact_sha256: str
    contract_version: str
    target_builder_version: str
    as_of_session: str
    allocation_contract_version: str
    allocation_sha256: str
    allocation_manifest_sha256: str
    scanner_snapshot_sha256: str
    positions_sha256: str
    portfolio_capital: float
    execution_state: str
    rows: tuple[OptimizerTargetRow, ...]

    @property
    def reference_prices(self) -> dict[str, float]:
        return {row.symbol: row.reference_price for row in self.rows}

    @property
    def current_positions(self) -> dict[str, float]:
        return {
            row.symbol: float(row.current_position)
            for row in self.rows
            if row.current_position > 0
        }

    @property
    def target_positions(self) -> dict[str, float]:
        return {
            row.symbol: float(row.target_shares)
            for row in self.rows
            if row.target_shares > 0
        }


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, *, field: str) -> str:
    normalized = str(value).strip()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized.lower()


def _require_finite_float(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _require_integer(value: Any, *, field: str) -> int:
    text = str(value).strip()
    if text == "":
        raise ValueError(f"{field} must be an integer")
    try:
        numeric = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError(f"{field} must be an integer")
    return int(numeric)


def _optional_positive_integer(value: Any, *, field: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    result = _require_integer(value, field=field)
    if result <= 0:
        raise ValueError(f"{field} must be positive when present")
    return result


def _close(left: float, right: float) -> bool:
    return math.isclose(
        float(left),
        float(right),
        rel_tol=0.0,
        abs_tol=_FLOAT_ABS_TOL,
    )


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"optimizer target manifest not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("optimizer target manifest contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("optimizer target manifest must contain a JSON object")

    missing = sorted(_REQUIRED_MANIFEST_FIELDS - set(payload))
    if missing:
        raise ValueError(
            "optimizer target manifest missing required fields: "
            + ", ".join(missing)
        )
    return payload


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    observed_artifact_sha256: str,
) -> None:
    if manifest["handoff_contract_version"] != PORTFOLIO_TARGET_HANDOFF_VERSION:
        raise ValueError(
            "optimizer handoff contract mismatch: "
            f"expected {PORTFOLIO_TARGET_HANDOFF_VERSION!r}"
        )

    state = str(manifest["execution_state"]).strip().upper()
    if state not in ALLOWED_EXECUTION_STATES:
        raise ValueError(
            "optimizer execution_state must be DRY_RUN or PAPER"
        )

    if manifest["broker_submission_permitted"] is not False:
        raise ValueError(
            "optimizer handoff must set broker_submission_permitted == false"
        )

    if manifest["immutable"] is not True:
        raise ValueError("optimizer handoff manifest must set immutable == true")

    expected_sha = _require_sha256(
        manifest["execution_safe_targets_sha256"],
        field="execution_safe_targets_sha256",
    )
    if expected_sha != observed_artifact_sha256:
        raise ValueError(
            "optimizer target artifact SHA-256 mismatch: "
            f"expected {expected_sha}, observed {observed_artifact_sha256}"
        )

    for field in (
        "allocation_sha256",
        "allocation_manifest_sha256",
        "scanner_snapshot_sha256",
        "positions_sha256",
    ):
        _require_sha256(manifest[field], field=field)

    if not str(manifest["target_builder_version"]).strip():
        raise ValueError("target_builder_version cannot be empty")
    if not str(manifest["as_of_session"]).strip():
        raise ValueError("as_of_session cannot be empty")
    if not str(manifest["allocation_contract_version"]).strip():
        raise ValueError("allocation_contract_version cannot be empty")

    capital = _require_finite_float(
        manifest["portfolio_capital"],
        field="portfolio_capital",
    )
    if capital <= 0:
        raise ValueError("portfolio_capital must be positive")

    for field in (
        "row_count",
        "target_symbol_count",
        "targeted_count",
        "zero_weight_count",
        "rounding_to_zero_count",
        "exit_count",
        "buy_count",
        "sell_count",
        "hold_count",
    ):
        value = _require_integer(manifest[field], field=field)
        if value < 0:
            raise ValueError(f"{field} cannot be negative")

    for field in (
        "target_notional",
        "residual_cash",
        "realized_weight_sum",
        "total_weight_rounding_error",
    ):
        _require_finite_float(manifest[field], field=field)

    generated = str(manifest["generated_at_utc"]).strip()
    try:
        parsed = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at_utc must be valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("generated_at_utc must include a timezone")


def _read_target_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"optimizer target artifact not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = tuple(reader.fieldnames or ())
        if actual != TARGET_COLUMNS:
            raise ValueError(
                "optimizer target columns do not match "
                "portfolio-target-handoff-v1 exactly"
            )
        rows = list(reader)

    if not rows:
        raise ValueError("optimizer target artifact is empty")
    return rows


def _validate_rows(
    source_rows: Iterable[dict[str, str]],
    manifest: dict[str, Any],
) -> tuple[OptimizerTargetRow, ...]:
    rows: list[OptimizerTargetRow] = []
    symbols: set[str] = set()

    expected_state = str(manifest["execution_state"]).strip().upper()
    expected_contract = str(manifest["handoff_contract_version"]).strip()
    expected_builder = str(manifest["target_builder_version"]).strip()
    expected_session = str(manifest["as_of_session"]).strip()
    expected_allocation_contract = str(
        manifest["allocation_contract_version"]
    ).strip()
    expected_allocation_sha = _require_sha256(
        manifest["allocation_sha256"],
        field="allocation_sha256",
    )
    expected_allocation_manifest_sha = _require_sha256(
        manifest["allocation_manifest_sha256"],
        field="allocation_manifest_sha256",
    )
    expected_scanner_sha = _require_sha256(
        manifest["scanner_snapshot_sha256"],
        field="scanner_snapshot_sha256",
    )
    expected_capital = _require_finite_float(
        manifest["portfolio_capital"],
        field="portfolio_capital",
    )

    status_counts = {status: 0 for status in ALLOWED_TARGET_STATUSES}
    side_counts = {side: 0 for side in ALLOWED_TRADE_SIDES}

    target_notional = 0.0
    realized_weight_sum = 0.0
    rounding_error_sum = 0.0
    target_symbol_count = 0
    approved_weight_sum = 0.0

    for index, source in enumerate(source_rows, start=2):
        prefix = f"optimizer target row {index}"

        static_expectations = {
            "handoff_contract_version": expected_contract,
            "target_builder_version": expected_builder,
            "as_of_session": expected_session,
            "allocation_contract_version": expected_allocation_contract,
            "allocation_sha256": expected_allocation_sha,
            "allocation_manifest_sha256": expected_allocation_manifest_sha,
            "scanner_snapshot_sha256": expected_scanner_sha,
            "execution_state": expected_state,
        }
        for field, expected in static_expectations.items():
            observed = str(source[field]).strip()
            if field.endswith("_sha256"):
                observed = observed.lower()
            if field == "execution_state":
                observed = observed.upper()
            if observed != expected:
                raise ValueError(
                    f"{prefix} {field} does not match manifest"
                )

        symbol = str(source["symbol"]).strip().upper()
        if not symbol:
            raise ValueError(f"{prefix} symbol cannot be empty")
        if symbol in symbols:
            raise ValueError(f"duplicate optimizer target symbol: {symbol}")
        symbols.add(symbol)

        scanner_rank = _optional_positive_integer(
            source["scanner_rank"],
            field=f"{prefix} scanner_rank",
        )
        weight = _require_finite_float(
            source["approved_target_weight"],
            field=f"{prefix} approved_target_weight",
        )
        if weight < -1e-12 or weight > 1 + 1e-12:
            raise ValueError(
                f"{prefix} approved_target_weight must be within [0, 1]"
            )

        price = _require_finite_float(
            source["reference_price"],
            field=f"{prefix} reference_price",
        )
        if price <= 0:
            raise ValueError(f"{prefix} reference_price must be positive")

        price_source = str(source["reference_price_source"]).strip()
        if price_source not in ALLOWED_REFERENCE_PRICE_SOURCES:
            raise ValueError(f"{prefix} reference_price_source is invalid")

        capital = _require_finite_float(
            source["portfolio_capital"],
            field=f"{prefix} portfolio_capital",
        )
        if not _close(capital, expected_capital):
            raise ValueError(f"{prefix} portfolio_capital does not match manifest")

        target_dollars = _require_finite_float(
            source["target_dollar_value"],
            field=f"{prefix} target_dollar_value",
        )
        target_shares = _require_integer(
            source["target_shares"],
            field=f"{prefix} target_shares",
        )
        target_share_notional = _require_finite_float(
            source["target_share_notional"],
            field=f"{prefix} target_share_notional",
        )
        realized_weight = _require_finite_float(
            source["realized_target_weight"],
            field=f"{prefix} realized_target_weight",
        )
        rounding_error = _require_finite_float(
            source["weight_rounding_error"],
            field=f"{prefix} weight_rounding_error",
        )
        current_position = _require_integer(
            source["current_position"],
            field=f"{prefix} current_position",
        )
        share_delta = _require_integer(
            source["share_delta"],
            field=f"{prefix} share_delta",
        )

        if target_dollars < -_FLOAT_ABS_TOL:
            raise ValueError(f"{prefix} target_dollar_value cannot be negative")
        if target_shares < 0:
            raise ValueError(f"{prefix} target_shares cannot be negative")
        if current_position < 0:
            raise ValueError(f"{prefix} current_position cannot be negative")
        if target_share_notional < -_FLOAT_ABS_TOL:
            raise ValueError(f"{prefix} target_share_notional cannot be negative")
        if realized_weight < -_FLOAT_ABS_TOL:
            raise ValueError(f"{prefix} realized_target_weight cannot be negative")
        if rounding_error < -_FLOAT_ABS_TOL:
            raise ValueError(f"{prefix} weight_rounding_error cannot be negative")

        if share_delta != target_shares - current_position:
            raise ValueError(
                f"{prefix} share_delta must equal "
                "target_shares - current_position"
            )

        expected_trade_side = (
            "BUY"
            if share_delta > 0
            else "SELL"
            if share_delta < 0
            else "HOLD"
        )
        trade_side = str(source["trade_side"]).strip().upper()
        if trade_side != expected_trade_side:
            raise ValueError(
                f"{prefix} trade_side does not match share_delta"
            )

        target_status = str(source["target_status"]).strip().upper()
        if target_status not in ALLOWED_TARGET_STATUSES:
            raise ValueError(f"{prefix} target_status is invalid")

        if target_status == "TARGETED":
            if weight <= 0 or target_shares <= 0:
                raise ValueError(f"{prefix} TARGETED semantics are invalid")
        elif target_status == "ROUNDING_TO_ZERO":
            if weight <= 0 or target_shares != 0:
                raise ValueError(
                    f"{prefix} ROUNDING_TO_ZERO semantics are invalid"
                )
        elif target_status == "EXIT":
            if weight > _FLOAT_ABS_TOL or current_position <= 0 or target_shares != 0:
                raise ValueError(f"{prefix} EXIT semantics are invalid")
        elif target_status == "ZERO_WEIGHT":
            if weight > _FLOAT_ABS_TOL or current_position != 0 or target_shares != 0:
                raise ValueError(f"{prefix} ZERO_WEIGHT semantics are invalid")

        if weight > _FLOAT_ABS_TOL and scanner_rank is None:
            raise ValueError(
                f"{prefix} positive target weight requires scanner_rank"
            )

        expected_target_dollars = expected_capital * weight
        expected_target_shares = math.floor(
            expected_target_dollars / price
        )
        expected_notional = target_shares * price
        expected_realized_weight = expected_notional / expected_capital
        expected_rounding_error = weight - expected_realized_weight

        if target_shares != expected_target_shares:
            raise ValueError(
                f"{prefix} target_shares violates frozen floor policy"
            )
        if not _close(target_dollars, expected_target_dollars):
            raise ValueError(f"{prefix} target_dollar_value invariant failed")
        if not _close(target_share_notional, expected_notional):
            raise ValueError(f"{prefix} target_share_notional invariant failed")
        if not _close(realized_weight, expected_realized_weight):
            raise ValueError(f"{prefix} realized_target_weight invariant failed")
        if not _close(rounding_error, expected_rounding_error):
            raise ValueError(f"{prefix} weight_rounding_error invariant failed")

        approved_weight_sum += weight
        target_notional += target_share_notional
        realized_weight_sum += realized_weight
        rounding_error_sum += rounding_error
        status_counts[target_status] += 1
        side_counts[trade_side] += 1
        if weight > _FLOAT_ABS_TOL:
            target_symbol_count += 1

        rows.append(
            OptimizerTargetRow(
                symbol=symbol,
                share_delta=share_delta,
                trade_side=trade_side,
                current_position=current_position,
                target_shares=target_shares,
                reference_price=price,
                approved_target_weight=weight,
                execution_state=expected_state,
            )
        )

    if not _close(approved_weight_sum, 1.0):
        raise ValueError(
            "optimizer approved_target_weight values must sum to 1.0"
        )

    expected_counts = {
        "row_count": len(rows),
        "target_symbol_count": target_symbol_count,
        "targeted_count": status_counts["TARGETED"],
        "zero_weight_count": status_counts["ZERO_WEIGHT"],
        "rounding_to_zero_count": status_counts["ROUNDING_TO_ZERO"],
        "exit_count": status_counts["EXIT"],
        "buy_count": side_counts["BUY"],
        "sell_count": side_counts["SELL"],
        "hold_count": side_counts["HOLD"],
    }
    for field, expected in expected_counts.items():
        observed = _require_integer(manifest[field], field=field)
        if observed != expected:
            raise ValueError(
                f"optimizer manifest {field} mismatch: "
                f"expected {expected}, observed {observed}"
            )

    residual_cash = expected_capital - target_notional
    accounting = {
        "target_notional": target_notional,
        "residual_cash": residual_cash,
        "realized_weight_sum": realized_weight_sum,
        "total_weight_rounding_error": rounding_error_sum,
    }
    for field, expected in accounting.items():
        observed = _require_finite_float(manifest[field], field=field)
        if not _close(observed, expected):
            raise ValueError(
                f"optimizer manifest {field} accounting invariant failed"
            )

    return tuple(rows)


def load_optimizer_target_handoff(
    *,
    target_csv: str | Path,
    manifest_json: str | Path,
    expected_artifact_sha256: str | None = None,
) -> OptimizerTargetHandoff:
    target_path = Path(target_csv)
    manifest_path = Path(manifest_json)

    observed_sha = sha256_file(target_path)
    if expected_artifact_sha256 is not None:
        pinned_sha = _require_sha256(
            expected_artifact_sha256,
            field="expected_artifact_sha256",
        )
        if pinned_sha != observed_sha:
            raise ValueError(
                "optimizer target artifact does not match pinned SHA-256"
            )

    manifest = _load_manifest(manifest_path)
    _validate_manifest(
        manifest,
        observed_artifact_sha256=observed_sha,
    )
    rows = _validate_rows(
        _read_target_rows(target_path),
        manifest,
    )

    return OptimizerTargetHandoff(
        target_path=target_path,
        manifest_path=manifest_path,
        artifact_sha256=observed_sha,
        contract_version=PORTFOLIO_TARGET_HANDOFF_VERSION,
        target_builder_version=str(manifest["target_builder_version"]).strip(),
        as_of_session=str(manifest["as_of_session"]).strip(),
        allocation_contract_version=str(
            manifest["allocation_contract_version"]
        ).strip(),
        allocation_sha256=_require_sha256(
            manifest["allocation_sha256"],
            field="allocation_sha256",
        ),
        allocation_manifest_sha256=_require_sha256(
            manifest["allocation_manifest_sha256"],
            field="allocation_manifest_sha256",
        ),
        scanner_snapshot_sha256=_require_sha256(
            manifest["scanner_snapshot_sha256"],
            field="scanner_snapshot_sha256",
        ),
        positions_sha256=_require_sha256(
            manifest["positions_sha256"],
            field="positions_sha256",
        ),
        portfolio_capital=_require_finite_float(
            manifest["portfolio_capital"],
            field="portfolio_capital",
        ),
        execution_state=str(manifest["execution_state"]).strip().upper(),
        rows=rows,
    )


def optimizer_targets_to_orders(
    handoff: OptimizerTargetHandoff,
) -> tuple[OrderRequest, ...]:
    candidates = [row for row in handoff.rows if row.share_delta != 0]
    candidates.sort(
        key=lambda row: (
            0 if row.share_delta < 0 else 1,
            row.symbol,
        )
    )

    orders: list[OrderRequest] = []
    artifact_tag = handoff.artifact_sha256[:16]
    for row in candidates:
        side = (
            OrderSide.BUY
            if row.share_delta > 0
            else OrderSide.SELL
        )
        quantity = abs(row.share_delta)
        order_id = (
            f"optimizer:{handoff.as_of_session}:{artifact_tag}:"
            f"{row.symbol}:{side.value}:{quantity}"
        )
        orders.append(
            OrderRequest(
                symbol=row.symbol,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET,
                order_id=order_id,
            )
        )

    return tuple(orders)
