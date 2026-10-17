from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from enum import Enum
from pathlib import Path
from typing import Iterable


CANDIDATE_ALLOCATION_COLUMNS = {
    "scanner_rank",
    "symbol",
    "scanner_score",
    "annualized_volatility",
    "target_weight",
}
REFERENCE_PRICE_COLUMNS = {"symbol", "reference_price"}
CURRENT_POSITION_COLUMNS = {"symbol", "current_position"}

EXECUTION_TARGET_COLUMNS = (
    "allocation_sha256",
    "symbol",
    "approved_target_weight",
    "reference_price",
    "portfolio_capital",
    "target_dollar_value",
    "target_shares",
    "current_position",
    "share_delta",
    "execution_state",
)

WEIGHT_TOLERANCE = Decimal("0.000001")


class ExecutionState(str, Enum):
    DRY_RUN = "DRY_RUN"
    PAPER = "PAPER"


@dataclass(frozen=True)
class ExecutionTargetRow:
    allocation_sha256: str
    symbol: str
    approved_target_weight: Decimal
    reference_price: Decimal
    portfolio_capital: Decimal
    target_dollar_value: Decimal
    target_shares: int
    current_position: int
    share_delta: int
    execution_state: ExecutionState

    def to_csv_row(self) -> dict[str, str | int]:
        return {
            "allocation_sha256": self.allocation_sha256,
            "symbol": self.symbol,
            "approved_target_weight": _decimal_text(
                self.approved_target_weight
            ),
            "reference_price": _money_text(self.reference_price),
            "portfolio_capital": _money_text(self.portfolio_capital),
            "target_dollar_value": _money_text(
                self.target_dollar_value
            ),
            "target_shares": self.target_shares,
            "current_position": self.current_position,
            "share_delta": self.share_delta,
            "execution_state": self.execution_state.value,
        }


@dataclass(frozen=True)
class ExecutionTargetBuild:
    rows: tuple[ExecutionTargetRow, ...]
    allocation_sha256: str
    reference_prices_sha256: str
    current_positions_sha256: str
    portfolio_capital: Decimal
    execution_state: ExecutionState


@dataclass(frozen=True)
class _Allocation:
    symbol: str
    rank: int
    target_weight: Decimal


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal(value: str, *, field: str, symbol: str | None = None) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        suffix = f" for {symbol}" if symbol else ""
        raise ValueError(f"invalid {field}{suffix}: {value!r}") from exc

    if not parsed.is_finite():
        suffix = f" for {symbol}" if symbol else ""
        raise ValueError(f"non-finite {field}{suffix}")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


def _money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _validate_columns(
    fieldnames: Iterable[str] | None,
    required: set[str],
    *,
    label: str,
) -> None:
    present = set(fieldnames or ())
    missing = sorted(required - present)
    if missing:
        raise ValueError(
            f"{label} missing required columns: {', '.join(missing)}"
        )


def _read_allocations(path: Path) -> list[_Allocation]:
    rows: list[_Allocation] = []
    seen: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_columns(
            reader.fieldnames,
            CANDIDATE_ALLOCATION_COLUMNS,
            label="candidate allocation",
        )

        for source in reader:
            symbol = (source["symbol"] or "").strip().upper()
            if not symbol:
                raise ValueError("candidate allocation contains blank symbol")
            if symbol in seen:
                raise ValueError(
                    f"candidate allocation contains duplicate symbol: {symbol}"
                )
            seen.add(symbol)

            try:
                rank = int(source["scanner_rank"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid scanner_rank for {symbol}"
                ) from exc
            if rank <= 0:
                raise ValueError(
                    f"scanner_rank must be positive for {symbol}"
                )

            weight = _decimal(
                source["target_weight"],
                field="target_weight",
                symbol=symbol,
            )
            if weight < 0 or weight > 1:
                raise ValueError(
                    f"target_weight must be between 0 and 1 for {symbol}"
                )

            rows.append(
                _Allocation(
                    symbol=symbol,
                    rank=rank,
                    target_weight=weight,
                )
            )

    if not rows:
        raise ValueError("candidate allocation is empty")

    weight_sum = sum(
        (row.target_weight for row in rows),
        start=Decimal("0"),
    )
    if abs(weight_sum - Decimal("1")) > WEIGHT_TOLERANCE:
        raise ValueError(
            "candidate allocation target weights must sum to 1; "
            f"observed {weight_sum}"
        )

    return rows


def _read_prices(path: Path) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_columns(
            reader.fieldnames,
            REFERENCE_PRICE_COLUMNS,
            label="reference prices",
        )

        for source in reader:
            symbol = (source["symbol"] or "").strip().upper()
            if not symbol:
                raise ValueError("reference prices contain blank symbol")
            if symbol in values:
                raise ValueError(
                    f"reference prices contain duplicate symbol: {symbol}"
                )

            price = _decimal(
                source["reference_price"],
                field="reference_price",
                symbol=symbol,
            )
            if price <= 0:
                raise ValueError(
                    f"reference_price must be positive for {symbol}"
                )
            values[symbol] = price

    return values


def _read_positions(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_columns(
            reader.fieldnames,
            CURRENT_POSITION_COLUMNS,
            label="current positions",
        )

        for source in reader:
            symbol = (source["symbol"] or "").strip().upper()
            if not symbol:
                raise ValueError("current positions contain blank symbol")
            if symbol in values:
                raise ValueError(
                    f"current positions contain duplicate symbol: {symbol}"
                )

            try:
                quantity = int(source["current_position"])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"current_position must be an integer for {symbol}"
                ) from exc
            if quantity < 0:
                raise ValueError(
                    f"current_position cannot be negative for {symbol}"
                )
            values[symbol] = quantity

    return values


def build_execution_target(
    *,
    allocation_csv: str | Path,
    reference_prices_csv: str | Path,
    current_positions_csv: str | Path,
    portfolio_capital: Decimal | str | float | int,
    execution_state: ExecutionState | str,
    expected_allocation_sha256: str | None = None,
) -> ExecutionTargetBuild:
    allocation_path = Path(allocation_csv)
    prices_path = Path(reference_prices_csv)
    positions_path = Path(current_positions_csv)

    for label, path in (
        ("allocation", allocation_path),
        ("reference prices", prices_path),
        ("current positions", positions_path),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} file not found: {path}")

    allocation_sha256 = _sha256(allocation_path)
    if expected_allocation_sha256 is not None:
        expected = expected_allocation_sha256.strip().lower()
        if allocation_sha256 != expected:
            raise ValueError(
                "candidate allocation SHA-256 mismatch: "
                f"expected {expected}, observed {allocation_sha256}"
            )

    try:
        state = (
            execution_state
            if isinstance(execution_state, ExecutionState)
            else ExecutionState(str(execution_state).upper())
        )
    except ValueError as exc:
        raise ValueError(
            "execution_state must be DRY_RUN or PAPER"
        ) from exc

    capital = _decimal(
        str(portfolio_capital),
        field="portfolio_capital",
    )
    if capital <= 0:
        raise ValueError("portfolio_capital must be positive")

    allocations = _read_allocations(allocation_path)
    prices = _read_prices(prices_path)
    positions = _read_positions(positions_path)

    allocation_by_symbol = {
        row.symbol: row
        for row in allocations
    }

    ordered_symbols = [
        row.symbol
        for row in sorted(
            allocations,
            key=lambda row: (row.rank, row.symbol),
        )
    ]
    liquidation_symbols = sorted(
        set(positions) - set(allocation_by_symbol)
    )
    ordered_symbols.extend(liquidation_symbols)

    missing_prices = sorted(
        symbol
        for symbol in ordered_symbols
        if symbol not in prices
    )
    if missing_prices:
        raise ValueError(
            "missing reference prices for: "
            + ", ".join(missing_prices)
        )

    rows: list[ExecutionTargetRow] = []
    for symbol in ordered_symbols:
        allocation = allocation_by_symbol.get(symbol)
        weight = (
            allocation.target_weight
            if allocation is not None
            else Decimal("0")
        )
        price = prices[symbol]
        target_dollar = (
            capital * weight
        ).quantize(Decimal("0.01"))

        raw_shares = target_dollar / price
        target_shares = int(
            raw_shares.to_integral_value(rounding=ROUND_DOWN)
        )

        current_position = positions.get(symbol, 0)
        share_delta = target_shares - current_position

        rows.append(
            ExecutionTargetRow(
                allocation_sha256=allocation_sha256,
                symbol=symbol,
                approved_target_weight=weight,
                reference_price=price,
                portfolio_capital=capital,
                target_dollar_value=target_dollar,
                target_shares=target_shares,
                current_position=current_position,
                share_delta=share_delta,
                execution_state=state,
            )
        )

    return ExecutionTargetBuild(
        rows=tuple(rows),
        allocation_sha256=allocation_sha256,
        reference_prices_sha256=_sha256(prices_path),
        current_positions_sha256=_sha256(positions_path),
        portfolio_capital=capital,
        execution_state=state,
    )


def write_execution_target(
    *,
    build: ExecutionTargetBuild,
    output_csv: str | Path,
    manifest_json: str | Path | None = None,
) -> tuple[Path, Path]:
    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=EXECUTION_TARGET_COLUMNS,
        )
        writer.writeheader()
        for row in build.rows:
            writer.writerow(row.to_csv_row())

    output_sha256 = _sha256(output_path)
    manifest_path = (
        Path(manifest_json)
        if manifest_json is not None
        else output_path.with_suffix(".manifest.json")
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "execution_target_contract": "execution-target-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "execution_state": build.execution_state.value,
        "portfolio_capital": _money_text(build.portfolio_capital),
        "row_count": len(build.rows),
        "allocation_sha256": build.allocation_sha256,
        "reference_prices_sha256": build.reference_prices_sha256,
        "current_positions_sha256": build.current_positions_sha256,
        "execution_target_sha256": output_sha256,
        "share_policy": "WHOLE_SHARES_FLOOR",
        "live_execution_allowed": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return output_path, manifest_path
