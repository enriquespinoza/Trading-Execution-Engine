from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.risk.limits import RiskLimits, evaluate_order


def test_rejects_order_over_notional_limit() -> None:
    order = OrderRequest("AAA", OrderSide.BUY, 300)
    decision = evaluate_order(
        order,
        price=100.0,
        positions={},
        limits=RiskLimits(max_order_notional=25_000.0),
    )
    assert decision.approved is False
    assert decision.reason == "max_order_notional_exceeded"


def test_rejects_short_sale_when_disabled() -> None:
    order = OrderRequest("AAA", OrderSide.SELL, 11)
    decision = evaluate_order(
        order,
        price=100.0,
        positions={"AAA": 10},
        limits=RiskLimits(allow_short_sales=False),
    )
    assert decision.approved is False
    assert decision.reason == "short_sale_not_allowed"
