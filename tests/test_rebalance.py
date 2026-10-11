from trading_execution_engine.models.order import OrderSide
from trading_execution_engine.models.portfolio import Position, TargetAllocation
from trading_execution_engine.reconciliation.rebalance import RebalanceConfig, build_rebalance_orders


def test_build_rebalance_orders_creates_expected_buy_and_sell() -> None:
    orders = build_rebalance_orders(
        portfolio_value=10_000,
        targets=[TargetAllocation("AAA", 0.60), TargetAllocation("BBB", 0.40)],
        positions=[Position("AAA", 40), Position("BBB", 60)],
        prices={"AAA": 100.0, "BBB": 100.0},
        config=RebalanceConfig(min_trade_notional=1.0),
    )

    assert [(o.symbol, o.side, o.quantity) for o in orders] == [
        ("AAA", OrderSide.BUY, 20),
        ("BBB", OrderSide.SELL, 20),
    ]


def test_rebalance_ignores_small_trade() -> None:
    orders = build_rebalance_orders(
        portfolio_value=1_000,
        targets=[TargetAllocation("AAA", 0.51)],
        positions=[Position("AAA", 5)],
        prices={"AAA": 100.0},
        config=RebalanceConfig(min_trade_notional=200.0),
    )
    assert orders == []
