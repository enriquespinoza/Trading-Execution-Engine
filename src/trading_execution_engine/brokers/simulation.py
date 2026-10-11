from __future__ import annotations

from typing import Mapping

from trading_execution_engine.brokers.base import Broker
from trading_execution_engine.models.order import Fill, OrderRequest


class SimulationBroker(Broker):
    """Deterministic immediate-fill broker for Phase 1 dry runs."""

    def __init__(self, prices: Mapping[str, float]) -> None:
        self._prices = {symbol.upper(): float(price) for symbol, price in prices.items()}
        self.fills: list[Fill] = []

    def submit_order(self, order: OrderRequest) -> Fill:
        if order.symbol not in self._prices:
            raise ValueError(f"no simulation price for {order.symbol}")

        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=self._prices[order.symbol],
        )
        self.fills.append(fill)
        return fill
