from __future__ import annotations

from abc import ABC, abstractmethod

from trading_execution_engine.models.order import Fill, OrderRequest


class Broker(ABC):
    @abstractmethod
    def submit_order(self, order: OrderRequest) -> Fill:
        raise NotImplementedError
