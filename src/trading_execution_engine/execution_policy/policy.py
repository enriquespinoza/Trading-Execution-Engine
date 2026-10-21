from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderType,
)


_PRICE_QUANTUM = Decimal("0.0001")


def _round_price(value: float) -> float:
    return float(
        Decimal(str(value)).quantize(
            _PRICE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    )


@dataclass(frozen=True)
class ExecutionOrderPolicy:
    """
    Deterministic policy for converting optimizer MARKET intents into
    reviewable execution orders.

    Basis-point tolerances are applied around the optimizer reference price:

        BUY  limit = reference * (1 + buy_limit_tolerance_bps / 10_000)
        SELL limit = reference * (1 - sell_limit_tolerance_bps / 10_000)

    MARKET behavior remains the default for backward compatibility.
    """

    use_limit_orders: bool = False
    buy_limit_tolerance_bps: float = 0.0
    sell_limit_tolerance_bps: float = 0.0

    def __post_init__(self) -> None:
        for field, value in (
            (
                "buy_limit_tolerance_bps",
                self.buy_limit_tolerance_bps,
            ),
            (
                "sell_limit_tolerance_bps",
                self.sell_limit_tolerance_bps,
            ),
        ):
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"{field} must be finite")
            if numeric < 0:
                raise ValueError(f"{field} cannot be negative")
            if numeric >= 10_000:
                raise ValueError(
                    f"{field} must be less than 10000"
                )


def apply_execution_order_policy(
    order: OrderRequest,
    *,
    reference_price: float,
    policy: ExecutionOrderPolicy,
) -> OrderRequest:
    """
    Apply execution-order policy without changing trade intent or order ID.

    The returned order is still only an OrderRequest. Broker submission
    authority is controlled elsewhere by the execution engine.
    """

    price = float(reference_price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError(
            "reference_price must be positive and finite"
        )

    if not policy.use_limit_orders:
        return order

    if order.order_type != OrderType.MARKET:
        raise ValueError(
            "execution-order policy expects MARKET source orders"
        )

    if order.side == OrderSide.BUY:
        limit_price = price * (
            1.0
            + float(policy.buy_limit_tolerance_bps)
            / 10_000.0
        )
    elif order.side == OrderSide.SELL:
        limit_price = price * (
            1.0
            - float(policy.sell_limit_tolerance_bps)
            / 10_000.0
        )
    else:
        raise ValueError(
            f"unsupported order side: {order.side}"
        )

    limit_price = _round_price(limit_price)
    if limit_price <= 0:
        raise ValueError(
            "execution policy produced a non-positive limit price"
        )

    return OrderRequest(
        symbol=order.symbol,
        side=order.side,
        quantity=order.quantity,
        order_type=OrderType.LIMIT,
        limit_price=limit_price,
        order_id=order.order_id,
    )
