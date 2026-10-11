import pytest

from trading_execution_engine.brokers.simulation import (
    SimulationBroker,
    SimulationConfig,
)
from trading_execution_engine.engine import (
    ExecutionControls,
    ExecutionEngine,
)
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
)
from trading_execution_engine.risk.limits import RiskLimits


def make_engine(prices, *, config=None, controls=None):
    broker = SimulationBroker(prices, config)
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=100_000.0),
        controls,
    )
    return broker, engine


def test_limit_buy_not_marketable_remains_unfilled():
    broker, engine = make_engine({"AAA": 100.0})
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        OrderType.LIMIT,
        limit_price=99.0,
        order_id="lim1",
    )
    report = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )
    assert report.results[0].status == OrderStatus.NOT_FILLED
    assert report.results[0].execution_reason == "limit_not_marketable"
    assert broker.fills == []


def test_limit_buy_marketable_fills():
    _, engine = make_engine({"AAA": 100.0})
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        OrderType.LIMIT,
        limit_price=101.0,
        order_id="lim2",
    )
    report = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )
    assert report.results[0].status == OrderStatus.FILLED


def test_slippage_and_fees_reduce_cash():
    broker, engine = make_engine(
        {"AAA": 100.0},
        config=SimulationConfig(
            slippage_bps=10.0,
            commission_per_order=1.0,
            commission_per_share=0.10,
        ),
    )
    account = AccountState(cash=2_000.0)
    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 10, order_id="costs")],
        prices={"AAA": 100.0},
        account=account,
    )
    fill = report.results[0].fill
    assert fill is not None
    assert fill.fill_price == pytest.approx(100.10)
    assert fill.fees == pytest.approx(2.0)
    assert report.ending_cash == pytest.approx(997.0)
    assert len(broker.fills) == 1


def test_duplicate_order_id_is_rejected_across_calls():
    broker, engine = make_engine({"AAA": 100.0})
    account = AccountState(cash=1_000.0)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="same")

    first = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    second = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )

    assert first.results[0].status == OrderStatus.FILLED
    assert second.results[0].status == OrderStatus.REJECTED
    assert second.results[0].execution_reason == "duplicate_order_id"
    assert len(broker.fills) == 1


def test_kill_switch_blocks_order():
    broker, engine = make_engine(
        {"AAA": 100.0},
        controls=ExecutionControls(kill_switch_engaged=True),
    )
    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1)],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )
    assert report.results[0].execution_reason == "kill_switch_engaged"
    assert broker.fills == []


def test_closed_session_blocks_order():
    broker, engine = make_engine(
        {"AAA": 100.0},
        controls=ExecutionControls(market_session_open=False),
    )
    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1)],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )
    assert report.results[0].execution_reason == "market_session_closed"
    assert broker.fills == []


def test_fractional_order_rejected_by_default():
    _, engine = make_engine({"AAA": 100.0})
    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1.5)],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )
    assert (
        report.results[0].execution_reason
        == "fractional_shares_not_allowed"
    )


def test_fractional_order_allowed_when_enabled():
    _, engine = make_engine(
        {"AAA": 100.0},
        controls=ExecutionControls(allow_fractional_shares=True),
    )
    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1.5)],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )
    assert report.results[0].status == OrderStatus.FILLED
    assert report.ending_positions["AAA"] == pytest.approx(1.5)
