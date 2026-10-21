from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


_PRICE_QUANTUM = Decimal("0.0001")


def _round_price(value: float) -> float:
    return float(
        Decimal(str(value)).quantize(
            _PRICE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
    )


class ProtectiveStopType(str, Enum):
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


@dataclass(frozen=True)
class StopPolicy:
    """
    Review-only protective stop policy.

    stop_distance_pct uses percentage points:
        8.0 -> stop 8% below the reference price.

    stop_limit_buffer_bps is applied below the stop trigger for STOP_LIMIT.
    """

    stop_type: ProtectiveStopType = ProtectiveStopType.STOP_LIMIT
    stop_distance_pct: float = 8.0
    stop_limit_buffer_bps: float = 50.0

    def __post_init__(self) -> None:
        distance = float(self.stop_distance_pct)
        buffer_bps = float(self.stop_limit_buffer_bps)

        if not math.isfinite(distance):
            raise ValueError(
                "stop_distance_pct must be finite"
            )
        if distance <= 0 or distance >= 100:
            raise ValueError(
                "stop_distance_pct must be within (0, 100)"
            )

        if not math.isfinite(buffer_bps):
            raise ValueError(
                "stop_limit_buffer_bps must be finite"
            )
        if buffer_bps < 0 or buffer_bps >= 10_000:
            raise ValueError(
                "stop_limit_buffer_bps must be within [0, 10000)"
            )

        if (
            self.stop_type == ProtectiveStopType.STOP
            and buffer_bps != 0
        ):
            raise ValueError(
                "STOP policy requires stop_limit_buffer_bps == 0"
            )


@dataclass(frozen=True)
class ProtectiveStopRecommendation:
    symbol: str
    quantity: int
    reference_price: float
    stop_type: ProtectiveStopType
    stop_price: float
    stop_limit_price: float | None
    method: str = "fixed_percent"
    review_only: bool = True
    broker_submission_permitted: bool = False

    def __post_init__(self) -> None:
        if not self.review_only:
            raise ValueError(
                "protective stops are review-only in Phase 2K"
            )
        if self.broker_submission_permitted:
            raise ValueError(
                "protective stop recommendation cannot permit broker submission"
            )


def recommend_protective_stop(
    *,
    symbol: str,
    quantity: int,
    reference_price: float,
    policy: StopPolicy,
) -> ProtectiveStopRecommendation:
    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")

    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError("quantity must be a whole integer")
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    price = float(reference_price)
    if not math.isfinite(price) or price <= 0:
        raise ValueError(
            "reference_price must be positive and finite"
        )

    stop_price = _round_price(
        price
        * (
            1.0
            - float(policy.stop_distance_pct)
            / 100.0
        )
    )

    stop_limit_price: float | None = None
    if policy.stop_type == ProtectiveStopType.STOP_LIMIT:
        stop_limit_price = _round_price(
            stop_price
            * (
                1.0
                - float(policy.stop_limit_buffer_bps)
                / 10_000.0
            )
        )
        if stop_limit_price <= 0:
            raise ValueError(
                "stop policy produced a non-positive stop-limit price"
            )

    return ProtectiveStopRecommendation(
        symbol=normalized_symbol,
        quantity=quantity,
        reference_price=_round_price(price),
        stop_type=policy.stop_type,
        stop_price=stop_price,
        stop_limit_price=stop_limit_price,
    )
