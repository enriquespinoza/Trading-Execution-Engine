from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from trading_execution_engine.integrations.optimizer_targets import (
    OptimizerTargetHandoff,
)
from trading_execution_engine.integrations.schwab.account_snapshot import (
    SchwabAccountSnapshot,
)
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderType,
)


@dataclass(frozen=True)
class SchwabOrderPreview:
    order: OrderRequest
    schwab_order_spec: dict[str, Any]
    optimizer_reference_price: float
    schwab_reference_price: float
    price_drift_pct: float
    estimated_notional: float
    position_before: int
    position_after: int
    cash_before: float
    cash_after: float
    approved: bool
    reason: str
    broker_submission_permitted: bool = False

    def __post_init__(self) -> None:
        if self.broker_submission_permitted:
            raise ValueError(
                "SchwabOrderPreview can never permit broker submission"
            )


def _schwab_equity_order_spec(order: OrderRequest) -> dict[str, Any]:
    if order.order_type != OrderType.MARKET:
        raise ValueError(
            "Schwab preflight v1 supports MARKET orders only"
        )
    if order.is_fractional:
        raise ValueError(
            "Schwab preflight v1 supports whole-share orders only"
        )

    instruction = (
        "BUY"
        if order.side == OrderSide.BUY
        else "SELL"
    )

    return {
        "orderType": "MARKET",
        "session": "NORMAL",
        "duration": "DAY",
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": instruction,
                "quantity": int(order.quantity),
                "instrument": {
                    "symbol": order.symbol,
                    "assetType": "EQUITY",
                },
            }
        ],
    }


def _validate_account_matches_handoff(
    *,
    handoff: OptimizerTargetHandoff,
    snapshot: SchwabAccountSnapshot,
) -> None:
    for row in handoff.rows:
        actual = snapshot.positions.get(row.symbol, 0)
        if actual != row.current_position:
            raise ValueError(
                "Schwab account position does not match optimizer handoff: "
                f"{row.symbol} expected {row.current_position}, observed {actual}"
            )


def build_schwab_order_previews(
    *,
    handoff: OptimizerTargetHandoff,
    snapshot: SchwabAccountSnapshot,
    orders: tuple[OrderRequest, ...],
    max_reference_price_drift_pct: float = 10.0,
) -> tuple[SchwabOrderPreview, ...]:
    """
    Build local broker-compatible previews.

    This function performs no network calls and exposes no order submission.
    """
    if handoff.execution_state not in {"DRY_RUN", "PAPER"}:
        raise ValueError("handoff execution state is not preflight-safe")
    if snapshot.broker_submission_permitted:
        raise ValueError("Schwab snapshot unexpectedly permits submission")
    if not math.isfinite(max_reference_price_drift_pct):
        raise ValueError("max_reference_price_drift_pct must be finite")
    if max_reference_price_drift_pct < 0:
        raise ValueError(
            "max_reference_price_drift_pct cannot be negative"
        )

    _validate_account_matches_handoff(
        handoff=handoff,
        snapshot=snapshot,
    )

    row_by_symbol = {row.symbol: row for row in handoff.rows}
    current_positions = dict(snapshot.positions)
    cash = float(snapshot.cash_balance)
    previews: list[SchwabOrderPreview] = []

    for order in orders:
        row = row_by_symbol.get(order.symbol)
        if row is None:
            raise ValueError(
                f"order symbol absent from optimizer handoff: {order.symbol}"
            )
        if order.symbol not in snapshot.prices:
            raise ValueError(
                f"Schwab snapshot missing quote for {order.symbol}"
            )

        expected_side = (
            OrderSide.BUY
            if row.share_delta > 0
            else OrderSide.SELL
        )
        expected_quantity = abs(row.share_delta)
        if row.share_delta == 0:
            raise ValueError(
                f"zero-delta symbol must not create an order: {order.symbol}"
            )
        if order.side != expected_side:
            raise ValueError(
                f"order side does not match optimizer delta: {order.symbol}"
            )
        if int(order.quantity) != expected_quantity or order.is_fractional:
            raise ValueError(
                f"order quantity does not match optimizer delta: {order.symbol}"
            )

        quote = float(snapshot.prices[order.symbol])
        optimizer_price = float(row.reference_price)
        drift_pct = (
            abs(quote - optimizer_price)
            / optimizer_price
            * 100.0
        )
        estimated_notional = quote * order.quantity

        position_before = int(
            current_positions.get(order.symbol, 0)
        )
        cash_before = cash
        approved = True
        reason = "approved"

        if drift_pct > max_reference_price_drift_pct:
            approved = False
            reason = "reference_price_drift_exceeded"

        if order.side == OrderSide.SELL:
            if order.quantity > position_before:
                approved = False
                reason = "insufficient_position"
            position_after = (
                position_before - int(order.quantity)
                if approved
                else position_before
            )
            cash_after = (
                cash_before + estimated_notional
                if approved
                else cash_before
            )
        else:
            if estimated_notional > cash_before + 1e-9:
                approved = False
                reason = "insufficient_cash"
            position_after = (
                position_before + int(order.quantity)
                if approved
                else position_before
            )
            cash_after = (
                cash_before - estimated_notional
                if approved
                else cash_before
            )

        preview = SchwabOrderPreview(
            order=order,
            schwab_order_spec=_schwab_equity_order_spec(order),
            optimizer_reference_price=optimizer_price,
            schwab_reference_price=quote,
            price_drift_pct=drift_pct,
            estimated_notional=estimated_notional,
            position_before=position_before,
            position_after=position_after,
            cash_before=cash_before,
            cash_after=cash_after,
            approved=approved,
            reason=reason,
        )
        previews.append(preview)

        if approved:
            cash = cash_after
            if position_after:
                current_positions[order.symbol] = position_after
            else:
                current_positions.pop(order.symbol, None)

    return tuple(previews)
