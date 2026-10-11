from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from trading_execution_engine.brokers.base import Broker
from trading_execution_engine.models.order import Fill, OrderRequest, OrderSide
from trading_execution_engine.risk.limits import RiskDecision, RiskLimits, evaluate_order


@dataclass(frozen=True)
class ExecutionResult:
    order: OrderRequest
    risk: RiskDecision
    fill: Fill | None


class ExecutionEngine:
    def __init__(self, broker: Broker, risk_limits: RiskLimits) -> None:
        self._broker = broker
        self._risk_limits = risk_limits

    def execute(
        self,
        orders: Sequence[OrderRequest],
        *,
        prices: Mapping[str, float],
        positions: Mapping[str, int],
    ) -> list[ExecutionResult]:
        working_positions = dict(positions)
        results: list[ExecutionResult] = []

        for order in orders:
            if order.symbol not in prices:
                raise ValueError(f"missing execution price for {order.symbol}")

            risk = evaluate_order(
                order,
                price=prices[order.symbol],
                positions=working_positions,
                limits=self._risk_limits,
            )

            if not risk.approved:
                results.append(ExecutionResult(order=order, risk=risk, fill=None))
                continue

            fill = self._broker.submit_order(order)
            signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            working_positions[fill.symbol] = working_positions.get(fill.symbol, 0) + signed_qty
            results.append(ExecutionResult(order=order, risk=risk, fill=fill))

        return results
