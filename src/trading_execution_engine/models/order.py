from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    order_id: str = ""

    def __post_init__(self) -> None:
        if not self.symbol or not self.symbol.strip():
            raise ValueError("symbol is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        object.__setattr__(self, "symbol", self.symbol.upper().strip())
        if not self.order_id:
            object.__setattr__(self, "order_id", str(uuid4()))


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    fill_price: float

    @property
    def notional(self) -> float:
        return self.quantity * self.fill_price
