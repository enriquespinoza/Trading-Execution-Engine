from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from trading_execution_engine.models.order import Fill, OrderSide


@dataclass
class AccountState:
    """Mutable execution-time account state used by the simulation engine."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise ValueError("cash cannot be negative")
        self.positions = {
            symbol.upper().strip(): float(quantity)
            for symbol, quantity in self.positions.items()
            if float(quantity) != 0.0
        }
        if any(quantity < 0 for quantity in self.positions.values()):
            raise ValueError("Phase 2 account state does not support short positions")

    @classmethod
    def from_mapping(
        cls,
        *,
        cash: float,
        positions: Mapping[str, float],
    ) -> "AccountState":
        return cls(cash=float(cash), positions=dict(positions))

    def apply_fill(self, fill: Fill) -> None:
        current_qty = self.positions.get(fill.symbol, 0.0)
        new_cash = self.cash + fill.cash_effect

        if new_cash < -1e-9:
            raise ValueError("fill would create negative cash")

        if fill.side == OrderSide.BUY:
            new_qty = current_qty + fill.quantity
        else:
            if fill.quantity > current_qty + 1e-9:
                raise ValueError("fill would create a short position")
            new_qty = current_qty - fill.quantity

        self.cash = max(0.0, new_cash)
        if abs(new_qty) < 1e-9:
            self.positions.pop(fill.symbol, None)
        else:
            self.positions[fill.symbol] = new_qty
