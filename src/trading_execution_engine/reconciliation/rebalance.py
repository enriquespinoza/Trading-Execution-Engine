from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.models.portfolio import Position, TargetAllocation


@dataclass(frozen=True)
class RebalanceConfig:
    min_trade_notional: float = 100.0


def build_rebalance_orders(
    *,
    portfolio_value: float,
    targets: Sequence[TargetAllocation],
    positions: Sequence[Position],
    prices: Mapping[str, float],
    config: RebalanceConfig | None = None,
) -> list[OrderRequest]:
    if portfolio_value <= 0:
        raise ValueError("portfolio_value must be positive")

    cfg = config or RebalanceConfig()
    target_weights = {t.symbol: t.weight for t in targets}
    if sum(target_weights.values()) > 1.0000001:
        raise ValueError("target weights cannot exceed 100%")

    current_qty = {p.symbol: p.quantity for p in positions}
    symbols = sorted(set(target_weights) | set(current_qty))
    orders: list[OrderRequest] = []

    for symbol in symbols:
        if symbol not in prices or prices[symbol] <= 0:
            raise ValueError(f"missing valid price for {symbol}")

        price = prices[symbol]
        desired_value = portfolio_value * target_weights.get(symbol, 0.0)
        desired_qty = math.floor(desired_value / price)
        delta_qty = desired_qty - current_qty.get(symbol, 0)

        if delta_qty == 0:
            continue

        trade_notional = abs(delta_qty) * price
        if trade_notional < cfg.min_trade_notional:
            continue

        orders.append(
            OrderRequest(
                symbol=symbol,
                side=OrderSide.BUY if delta_qty > 0 else OrderSide.SELL,
                quantity=abs(delta_qty),
            )
        )

    return orders
