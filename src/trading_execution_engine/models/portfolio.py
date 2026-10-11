from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.upper().strip())


@dataclass(frozen=True)
class TargetAllocation:
    symbol: str
    weight: float

    def __post_init__(self) -> None:
        symbol = self.symbol.upper().strip()
        if not symbol:
            raise ValueError("symbol is required")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("weight must be between 0 and 1")
        object.__setattr__(self, "symbol", symbol)
