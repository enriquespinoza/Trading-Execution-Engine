from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from trading_execution_engine.models.order import Fill, OrderRequest


@dataclass(frozen=True)
class OrderPreview:
    fillable: bool
    estimated_fill_price: float
    estimated_fees: float
    reason: str = "fillable"


class Broker(ABC):
    @abstractmethod
    def preview_order(self, order: OrderRequest) -> OrderPreview:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> Fill | None:
        raise NotImplementedError
