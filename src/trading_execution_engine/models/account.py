from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from trading_execution_engine.models.order import Fill, OrderSide


@dataclass
class AccountState:
    """Mutable execution-time account state used by the simulation engine."""

    cash: float
    positions: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise ValueError("cash cannot be negative")
        self.positions = {
            symbol.upper().strip(): int(quantity)
            for symbol, quantity in self.positions.items()
            if int(quantity) != 0
        }
        if any(quantity < 0 for quantity in self.positions.values()):
            raise ValueError("Phase 2 account state does not support short positions")

    @classmethod
    def from_mapping(cls, *, cash: float, positions: Mapping[str, int]) -> "AccountState":
        return cls(cash=float(cash), positions=dict(positions))

    def apply_fill(self, fill: Fill) -> None:
        current_qty = self.positions.get(fill.symbol, 0)

        if fill.side == OrderSide.BUY:
            if fill.notional > self.cash + 1e-9:
                raise ValueError("fill would create negative cash")
            self.cash -= fill.notional
            new_qty = current_qty + fill.quantity
        else:
            if fill.quantity > current_qty:
                raise ValueError("fill would create a short position")
            self.cash += fill.notional
            new_qty = current_qty - fill.quantity

        if new_qty == 0:
            self.positions.pop(fill.symbol, None)
        else:
            self.positions[fill.symbol] = new_qty
