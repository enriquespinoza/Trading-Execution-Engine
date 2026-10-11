from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    REJECTED = "REJECTED"
    NOT_FILLED = "NOT_FILLED"
    FILLED = "FILLED"


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    order_id: str = ""

    def __post_init__(self) -> None:
        if not self.symbol or not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type == OrderType.LIMIT:
            if self.limit_price is None or self.limit_price <= 0:
                raise ValueError("positive limit_price is required for LIMIT orders")
        elif self.limit_price is not None:
            raise ValueError("limit_price is only valid for LIMIT orders")

        object.__setattr__(self, "symbol", self.symbol.upper().strip())
        object.__setattr__(self, "quantity", float(self.quantity))
        if not self.order_id:
            object.__setattr__(self, "order_id", str(uuid4()))

    @property
    def is_fractional(self) -> bool:
        return not self.quantity.is_integer()


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    fill_price: float
    fees: float = 0.0

    @property
    def notional(self) -> float:
        return self.quantity * self.fill_price

    @property
    def cash_effect(self) -> float:
        if self.side == OrderSide.BUY:
            return -(self.notional + self.fees)
        return self.notional - self.fees
