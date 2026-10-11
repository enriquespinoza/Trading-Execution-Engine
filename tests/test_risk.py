from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.risk.limits import RiskLimits, evaluate_order


def test_rejects_order_above_notional_limit() -> None:
    decision = evaluate_order(
        OrderRequest("AAA", OrderSide.BUY, 100),
        price=100.0,
        positions={},
        limits=RiskLimits(max_order_notional=5_000.0),
        available_cash=20_000.0,
    )
    assert decision.approved is False
    assert decision.reason == "max_order_notional_exceeded"


def test_rejects_short_sale_when_disabled() -> None:
    decision = evaluate_order(
        OrderRequest("AAA", OrderSide.SELL, 11),
        price=100.0,
        positions={"AAA": 10},
        limits=RiskLimits(allow_short_sales=False),
        available_cash=0.0,
    )
    assert decision.approved is False
    assert decision.reason == "short_sale_not_allowed"


def test_rejects_buy_when_available_cash_is_insufficient() -> None:
    decision = evaluate_order(
        OrderRequest("AAA", OrderSide.BUY, 6),
        price=100.0,
        positions={},
        limits=RiskLimits(max_order_notional=5_000.0),
        available_cash=500.0,
    )
    assert decision.approved is False
    assert decision.reason == "insufficient_cash"
