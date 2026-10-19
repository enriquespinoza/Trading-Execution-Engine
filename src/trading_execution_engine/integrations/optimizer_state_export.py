from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from trading_execution_engine.integrations.schwab.market_data import (
    SchwabMarketSnapshot,
)
from trading_execution_engine.simulation.persistent_account import (
    PersistentSimulationAccount,
)


POSITION_SNAPSHOT_CONTRACT = "paper-optimizer-position-snapshot-v1"
POSITION_COLUMNS = (
    "symbol",
    "current_position",
    "reference_price",
)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class OptimizerPositionExport:
    positions_path: Path
    manifest_path: Path
    positions_sha256: str
    manifest_sha256: str
    portfolio_capital: float
    cash: float
    position_market_value: float
    position_count: int
    paper_state_sha256: str
    market_snapshot_sha256: str


def _whole_nonnegative_quantity(value: float, symbol: str) -> int:
    quantity = float(value)
    if not math.isfinite(quantity):
        raise ValueError(f"position quantity must be finite: {symbol}")
    if quantity < 0:
        raise ValueError(f"short positions are not supported: {symbol}")
    if not quantity.is_integer():
        raise ValueError(f"fractional positions are not supported: {symbol}")
    return int(quantity)


def _validate_market_coverage(
    *,
    state: PersistentSimulationAccount,
    market: SchwabMarketSnapshot,
) -> None:
    held = {
        symbol
        for symbol, quantity in state.positions.items()
        if float(quantity) > 0
    }
    missing = sorted(held - set(market.prices))
    if missing:
        raise ValueError(
            "market snapshot missing held paper positions: "
            + ", ".join(missing)
        )


def build_optimizer_position_rows(
    *,
    state: PersistentSimulationAccount,
    market: SchwabMarketSnapshot,
) -> tuple[list[dict[str, object]], float]:
    _validate_market_coverage(
        state=state,
        market=market,
    )

    rows: list[dict[str, object]] = []
    market_value = 0.0

    for symbol in sorted(state.positions):
        quantity = _whole_nonnegative_quantity(
            state.positions[symbol],
            symbol,
        )
        if quantity == 0:
            continue

        price = float(market.prices[symbol])
        if not math.isfinite(price) or price <= 0:
            raise ValueError(
                f"reference price must be positive and finite: {symbol}"
            )

        market_value += quantity * price
        rows.append(
            {
                "symbol": symbol,
                "current_position": quantity,
                "reference_price": price,
            }
        )

    return rows, market_value


def write_optimizer_position_export(
    *,
    state: PersistentSimulationAccount,
    market: SchwabMarketSnapshot,
    output_dir: str | Path,
    generated_at_utc: datetime | None = None,
) -> OptimizerPositionExport:
    output_dir = Path(output_dir)
    positions_path = output_dir / "managed_sleeve_positions.csv"
    manifest_path = output_dir / "manifest.json"

    if positions_path.exists() or manifest_path.exists():
        raise FileExistsError(
            f"optimizer position export already exists: {output_dir}"
        )

    rows, position_market_value = build_optimizer_position_rows(
        state=state,
        market=market,
    )
    portfolio_capital = float(state.cash) + position_market_value

    if not math.isfinite(portfolio_capital) or portfolio_capital <= 0:
        raise ValueError(
            "paper portfolio capital must be positive and finite"
        )

    output_dir.mkdir(parents=True, exist_ok=False)

    with positions_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=POSITION_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    positions_sha = sha256_file(positions_path)
    generated_at = generated_at_utc or datetime.now(timezone.utc)
    if generated_at.tzinfo is None:
        raise ValueError("generated_at_utc must be timezone-aware")

    manifest = {
        "position_snapshot_contract": POSITION_SNAPSHOT_CONTRACT,
        "generated_at_utc": generated_at.astimezone(
            timezone.utc
        ).isoformat(),
        "immutable": True,
        "broker_submission_permitted": False,
        "paper_state_version": state.state_version,
        "paper_state_sha256": state.state_sha256,
        "paper_previous_state_sha256": state.previous_state_sha256,
        "source_optimizer_artifact_sha256": (
            state.source_artifact_sha256
        ),
        "market_snapshot_sha256": market.snapshot_sha256,
        "market_captured_at_utc": (
            market.captured_at_utc.astimezone(
                timezone.utc
            ).isoformat()
        ),
        "cash": float(state.cash),
        "position_market_value": position_market_value,
        "portfolio_capital": portfolio_capital,
        "position_count": len(rows),
        "positions_filename": positions_path.name,
        "positions_sha256": positions_sha,
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return OptimizerPositionExport(
        positions_path=positions_path,
        manifest_path=manifest_path,
        positions_sha256=positions_sha,
        manifest_sha256=sha256_file(manifest_path),
        portfolio_capital=portfolio_capital,
        cash=float(state.cash),
        position_market_value=position_market_value,
        position_count=len(rows),
        paper_state_sha256=state.state_sha256,
        market_snapshot_sha256=market.snapshot_sha256,
    )
