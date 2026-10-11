from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trading_execution_engine.models.order import OrderRequest, OrderSide


@dataclass(frozen=True)
class RiskLimits:
    max_order_notional: float = 25_000.0
    allow_short_sales: bool = False


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str


def evaluate_order(
    order: OrderRequest,
    *,
    price: float,
    positions: Mapping[str, int],
    limits: RiskLimits,
) -> RiskDecision:
    if price <= 0:
        return RiskDecision(False, "invalid_price")

    if order.quantity * price > limits.max_order_notional:
        return RiskDecision(False, "max_order_notional_exceeded")

    current_qty = positions.get(order.symbol, 0)
    if (
        order.side == OrderSide.SELL
        and not limits.allow_short_sales
        and order.quantity > current_qty
    ):
        return RiskDecision(False, "short_sale_not_allowed")

    return RiskDecision(True, "approved")
