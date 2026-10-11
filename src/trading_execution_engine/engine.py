from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from trading_execution_engine.brokers.base import Broker
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import Fill, OrderRequest, OrderSide
from trading_execution_engine.risk.limits import RiskDecision, RiskLimits, evaluate_order


@dataclass(frozen=True)
class ExecutionResult:
    order: OrderRequest
    risk: RiskDecision
    fill: Fill | None
    cash_after: float


@dataclass(frozen=True)
class ExecutionReport:
    results: tuple[ExecutionResult, ...]
    starting_cash: float
    ending_cash: float
    ending_positions: Mapping[str, int]

    @property
    def approved_count(self) -> int:
        return sum(result.risk.approved for result in self.results)

    @property
    def rejected_count(self) -> int:
        return len(self.results) - self.approved_count


class ExecutionEngine:
    def __init__(self, broker: Broker, risk_limits: RiskLimits) -> None:
        self._broker = broker
        self._risk_limits = risk_limits

    def execute(
        self,
        orders: Sequence[OrderRequest],
        *,
        prices: Mapping[str, float],
        account: AccountState,
    ) -> ExecutionReport:
        """Execute a rebalance deterministically: sells first, then buys."""

        starting_cash = account.cash
        results: list[ExecutionResult] = []

        ordered = [o for o in orders if o.side == OrderSide.SELL]
        ordered.extend(o for o in orders if o.side == OrderSide.BUY)

        for order in ordered:
            if order.symbol not in prices:
                raise ValueError(f"missing execution price for {order.symbol}")

            price = prices[order.symbol]
            risk = evaluate_order(
                order,
                price=price,
                positions=account.positions,
                limits=self._risk_limits,
                available_cash=account.cash,
            )

            if not risk.approved:
                results.append(
                    ExecutionResult(
                        order=order,
                        risk=risk,
                        fill=None,
                        cash_after=account.cash,
                    )
                )
                continue

            fill = self._broker.submit_order(order)
            account.apply_fill(fill)
            results.append(
                ExecutionResult(
                    order=order,
                    risk=risk,
                    fill=fill,
                    cash_after=account.cash,
                )
            )

        return ExecutionReport(
            results=tuple(results),
            starting_cash=starting_cash,
            ending_cash=account.cash,
            ending_positions=dict(account.positions),
        )
