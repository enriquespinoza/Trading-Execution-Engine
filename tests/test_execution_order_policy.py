import pytest

from trading_execution_engine.execution_policy.policy import (
    ExecutionOrderPolicy,
    apply_execution_order_policy,
)
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderType,
)


def test_market_behavior_remains_default() -> None:
    order = OrderRequest(
        "ABC",
        OrderSide.BUY,
        10,
        order_id="stable-order-id",
    )

    result = apply_execution_order_policy(
        order,
        reference_price=100.0,
        policy=ExecutionOrderPolicy(),
    )

    assert result is order
    assert result.order_type == OrderType.MARKET
    assert result.order_id == "stable-order-id"


def test_buy_limit_caps_execution_at_configured_tolerance() -> None:
    order = OrderRequest(
        "ABC",
        OrderSide.BUY,
        10,
        order_id="buy-order",
    )

    result = apply_execution_order_policy(
        order,
        reference_price=100.0,
        policy=ExecutionOrderPolicy(
            use_limit_orders=True,
            buy_limit_tolerance_bps=25,
        ),
    )

    assert result.order_type == OrderType.LIMIT
    assert result.limit_price == 100.25
    assert result.order_id == "buy-order"


def test_sell_limit_sets_configured_floor() -> None:
    order = OrderRequest(
        "ABC",
        OrderSide.SELL,
        10,
        order_id="sell-order",
    )

    result = apply_execution_order_policy(
        order,
        reference_price=100.0,
        policy=ExecutionOrderPolicy(
            use_limit_orders=True,
            sell_limit_tolerance_bps=25,
        ),
    )

    assert result.order_type == OrderType.LIMIT
    assert result.limit_price == 99.75
    assert result.order_id == "sell-order"


@pytest.mark.parametrize(
    "field,value",
    [
        ("buy_limit_tolerance_bps", -1),
        ("sell_limit_tolerance_bps", -1),
        ("buy_limit_tolerance_bps", 10_000),
        ("sell_limit_tolerance_bps", 10_000),
    ],
)
def test_invalid_limit_tolerance_fails_closed(
    field: str,
    value: float,
) -> None:
    kwargs = {field: value}

    with pytest.raises(ValueError):
        ExecutionOrderPolicy(**kwargs)


def test_policy_rejects_non_positive_reference_price() -> None:
    order = OrderRequest(
        "ABC",
        OrderSide.BUY,
        1,
    )

    with pytest.raises(
        ValueError,
        match="reference_price",
    ):
        apply_execution_order_policy(
            order,
            reference_price=0.0,
            policy=ExecutionOrderPolicy(
                use_limit_orders=True,
            ),
        )
