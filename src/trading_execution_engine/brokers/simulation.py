from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trading_execution_engine.brokers.base import Broker, OrderPreview
from trading_execution_engine.models.order import (
    Fill,
    OrderRequest,
    OrderSide,
    OrderType,
)


@dataclass(frozen=True)
class SimulationConfig:
    slippage_bps: float = 0.0
    commission_per_order: float = 0.0
    commission_per_share: float = 0.0

    def __post_init__(self) -> None:
        if self.slippage_bps < 0:
            raise ValueError("slippage_bps cannot be negative")
        if self.commission_per_order < 0 or self.commission_per_share < 0:
            raise ValueError("commissions cannot be negative")


class SimulationBroker(Broker):
    """Deterministic broker used only for simulation and dry runs."""

    def __init__(
        self,
        prices: Mapping[str, float],
        config: SimulationConfig | None = None,
    ) -> None:
        self._prices = {
            symbol.upper(): float(price)
            for symbol, price in prices.items()
        }
        self._config = config or SimulationConfig()
        self.fills: list[Fill] = []

    def _market_price(self, order: OrderRequest) -> float:
        if order.symbol not in self._prices:
            raise ValueError(f"no simulation price for {order.symbol}")
        price = self._prices[order.symbol]
        if price <= 0:
            raise ValueError(f"invalid simulation price for {order.symbol}")
        return price

    def _slipped_price(self, order: OrderRequest, market_price: float) -> float:
        slippage = self._config.slippage_bps / 10_000.0
        multiplier = (
            1.0 + slippage
            if order.side == OrderSide.BUY
            else 1.0 - slippage
        )
        return market_price * multiplier

    def _fees(self, order: OrderRequest) -> float:
        return self._config.commission_per_order + (
            self._config.commission_per_share * order.quantity
        )

    def preview_order(self, order: OrderRequest) -> OrderPreview:
        market_price = self._market_price(order)
        fill_price = self._slipped_price(order, market_price)
        fees = self._fees(order)

        if order.order_type == OrderType.LIMIT:
            assert order.limit_price is not None
            if (
                order.side == OrderSide.BUY
                and fill_price > order.limit_price
            ):
                return OrderPreview(
                    False,
                    fill_price,
                    fees,
                    "limit_not_marketable",
                )
            if (
                order.side == OrderSide.SELL
                and fill_price < order.limit_price
            ):
                return OrderPreview(
                    False,
                    fill_price,
                    fees,
                    "limit_not_marketable",
                )

        return OrderPreview(True, fill_price, fees)

    def submit_order(self, order: OrderRequest) -> Fill | None:
        preview = self.preview_order(order)
        if not preview.fillable:
            return None

        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=preview.estimated_fill_price,
            fees=preview.estimated_fees,
        )
        self.fills.append(fill)
        return fill
