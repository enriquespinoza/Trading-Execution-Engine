from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.models.portfolio import Position, TargetAllocation


@dataclass(frozen=True)
class RebalanceConfig:
    min_trade_notional: float = 100.0


@dataclass(frozen=True)
class ReconciliationLine:
    symbol: str
    target_weight: float
    actual_weight: float
    weight_drift: float
    quantity: int
    market_value: float


@dataclass(frozen=True)
class ReconciliationReport:
    portfolio_value: float
    cash: float
    cash_weight: float
    lines: tuple[ReconciliationLine, ...]


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


def reconcile_portfolio(
    *,
    targets: Sequence[TargetAllocation],
    positions: Mapping[str, int],
    cash: float,
    prices: Mapping[str, float],
) -> ReconciliationReport:
    if cash < 0:
        raise ValueError("cash cannot be negative")

    target_weights = {target.symbol: target.weight for target in targets}
    symbols = sorted(set(target_weights) | set(positions))

    market_values: dict[str, float] = {}
    for symbol in symbols:
        if symbol not in prices or prices[symbol] <= 0:
            raise ValueError(f"missing valid price for {symbol}")
        market_values[symbol] = positions.get(symbol, 0) * prices[symbol]

    portfolio_value = cash + sum(market_values.values())
    if portfolio_value <= 0:
        raise ValueError("portfolio value must be positive")

    lines = tuple(
        ReconciliationLine(
            symbol=symbol,
            target_weight=target_weights.get(symbol, 0.0),
            actual_weight=market_values[symbol] / portfolio_value,
            weight_drift=(market_values[symbol] / portfolio_value)
            - target_weights.get(symbol, 0.0),
            quantity=positions.get(symbol, 0),
            market_value=market_values[symbol],
        )
        for symbol in symbols
    )

    return ReconciliationReport(
        portfolio_value=portfolio_value,
        cash=cash,
        cash_weight=cash / portfolio_value,
        lines=lines,
    )
