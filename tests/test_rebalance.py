import pytest

from trading_execution_engine.models.order import OrderSide
from trading_execution_engine.models.portfolio import Position, TargetAllocation
from trading_execution_engine.reconciliation.rebalance import (
    RebalanceConfig,
    build_rebalance_orders,
    reconcile_portfolio,
)


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


def test_rebalance_fully_liquidates_position_missing_from_targets() -> None:
    orders = build_rebalance_orders(
        portfolio_value=10_000,
        targets=[TargetAllocation("AAA", 1.0)],
        positions=[Position("AAA", 50), Position("OLD", 20)],
        prices={"AAA": 100.0, "OLD": 50.0},
        config=RebalanceConfig(min_trade_notional=1.0),
    )

    assert ("OLD", OrderSide.SELL, 20) in [
        (order.symbol, order.side, order.quantity) for order in orders
    ]


def test_reconcile_portfolio_reports_actual_weights_and_cash() -> None:
    report = reconcile_portfolio(
        targets=[TargetAllocation("AAA", 0.50), TargetAllocation("BBB", 0.40)],
        positions={"AAA": 5, "BBB": 4},
        cash=100.0,
        prices={"AAA": 100.0, "BBB": 100.0},
    )

    assert report.portfolio_value == 1_000.0
    assert report.cash_weight == pytest.approx(0.10)
    by_symbol = {line.symbol: line for line in report.lines}
    assert by_symbol["AAA"].actual_weight == pytest.approx(0.50)
    assert by_symbol["AAA"].weight_drift == pytest.approx(0.0)
    assert by_symbol["BBB"].actual_weight == pytest.approx(0.40)
    assert by_symbol["BBB"].weight_drift == pytest.approx(0.0)
