from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from trading_execution_engine.models.order import OrderRequest


@dataclass(frozen=True)
class PreTradeAlert:
    order: OrderRequest
    estimated_fill_price: float
    estimated_fees: float
    available_cash: float

    @property
    def estimated_notional(self) -> float:
        return self.order.quantity * self.estimated_fill_price

    def to_message(self) -> str:
        limit_text = ""
        if self.order.limit_price is not None:
            limit_text = f" limit=${self.order.limit_price:,.2f}"

        return (
            "PRE-TRADE ALERT | "
            f"{self.order.side.value} {self.order.quantity:g} "
            f"{self.order.symbol} {self.order.order_type.value}"
            f"{limit_text} | est price=${self.estimated_fill_price:,.2f} "
            f"notional=${self.estimated_notional:,.2f} "
            f"fees=${self.estimated_fees:,.2f} | "
            f"order_id={self.order.order_id}"
        )


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    reason: str
    provider_message_id: str | None = None


class TradeNotifier(ABC):
    @abstractmethod
    def send_message(self, message: str) -> NotificationResult:
        raise NotImplementedError

    def send(self, alert: PreTradeAlert) -> NotificationResult:
        return self.send_message(alert.to_message())

    def send_approval_request(
        self,
        message: str,
        *,
        approval_code: str,
    ) -> NotificationResult:
        """Provider hook for interactive approval notifications.

        Providers without action-button support can fall back to plain text.
        """
        return self.send_message(message)
