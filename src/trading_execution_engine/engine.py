from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from trading_execution_engine.brokers.base import Broker
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import (
    Fill,
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from trading_execution_engine.risk.limits import (
    RiskDecision,
    RiskLimits,
    evaluate_order,
)


@dataclass(frozen=True)
class ExecutionControls:
    market_session_open: bool = True
    kill_switch_engaged: bool = False
    allow_fractional_shares: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    order: OrderRequest
    risk: RiskDecision
    fill: Fill | None
    cash_after: float
    status: OrderStatus
    execution_reason: str


@dataclass(frozen=True)
class ExecutionReport:
    results: tuple[ExecutionResult, ...]
    starting_cash: float
    ending_cash: float
    ending_positions: Mapping[str, float]

    @property
    def filled_count(self) -> int:
        return sum(
            result.status == OrderStatus.FILLED
            for result in self.results
        )

    @property
    def rejected_count(self) -> int:
        return sum(
            result.status == OrderStatus.REJECTED
            for result in self.results
        )


class ExecutionEngine:
    def __init__(
        self,
        broker: Broker,
        risk_limits: RiskLimits,
        controls: ExecutionControls | None = None,
    ) -> None:
        self._broker = broker
        self._risk_limits = risk_limits
        self._controls = controls or ExecutionControls()
        self._processed_order_ids: set[str] = set()

    def _control_decision(self, order: OrderRequest) -> RiskDecision:
        if self._controls.kill_switch_engaged:
            return RiskDecision(False, "kill_switch_engaged")

        if not self._controls.market_session_open:
            return RiskDecision(False, "market_session_closed")

        if (
            not self._controls.allow_fractional_shares
            and order.is_fractional
        ):
            return RiskDecision(
                False,
                "fractional_shares_not_allowed",
            )

        if order.order_id in self._processed_order_ids:
            return RiskDecision(False, "duplicate_order_id")

        return RiskDecision(True, "approved")

    def execute(
        self,
        orders: Sequence[OrderRequest],
        *,
        prices: Mapping[str, float],
        account: AccountState,
    ) -> ExecutionReport:
        """Execute deterministically with safety gates and sells first."""

        starting_cash = account.cash
        results: list[ExecutionResult] = []

        ordered = [o for o in orders if o.side == OrderSide.SELL]
        ordered.extend(o for o in orders if o.side == OrderSide.BUY)

        for order in ordered:
            if order.symbol not in prices:
                raise ValueError(
                    f"missing execution price for {order.symbol}"
                )

            control = self._control_decision(order)
            if not control.approved:
                results.append(
                    ExecutionResult(
                        order=order,
                        risk=control,
                        fill=None,
                        cash_after=account.cash,
                        status=OrderStatus.REJECTED,
                        execution_reason=control.reason,
                    )
                )
                continue

            preview = self._broker.preview_order(order)
            risk = evaluate_order(
                order,
                price=preview.estimated_fill_price,
                positions=account.positions,
                limits=self._risk_limits,
                available_cash=account.cash,
                estimated_fees=preview.estimated_fees,
            )

            if not risk.approved:
                results.append(
                    ExecutionResult(
                        order=order,
                        risk=risk,
                        fill=None,
                        cash_after=account.cash,
                        status=OrderStatus.REJECTED,
                        execution_reason=risk.reason,
                    )
                )
                continue

            self._processed_order_ids.add(order.order_id)

            if not preview.fillable:
                results.append(
                    ExecutionResult(
                        order=order,
                        risk=risk,
                        fill=None,
                        cash_after=account.cash,
                        status=OrderStatus.NOT_FILLED,
                        execution_reason=preview.reason,
                    )
                )
                continue

            fill = self._broker.submit_order(order)
            if fill is None:
                results.append(
                    ExecutionResult(
                        order=order,
                        risk=risk,
                        fill=None,
                        cash_after=account.cash,
                        status=OrderStatus.NOT_FILLED,
                        execution_reason="broker_not_filled",
                    )
                )
                continue

            account.apply_fill(fill)
            results.append(
                ExecutionResult(
                    order=order,
                    risk=risk,
                    fill=fill,
                    cash_after=account.cash,
                    status=OrderStatus.FILLED,
                    execution_reason="filled",
                )
            )

        return ExecutionReport(
            results=tuple(results),
            starting_cash=starting_cash,
            ending_cash=account.cash,
            ending_positions=dict(account.positions),
        )
