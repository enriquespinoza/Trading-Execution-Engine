from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionEngine
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.risk.limits import RiskLimits


def test_engine_executes_approved_order_and_updates_cash() -> None:
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(broker, RiskLimits(max_order_notional=5_000.0))
    account = AccountState(cash=2_000.0, positions={})

    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 10)],
        prices={"AAA": 100.0},
        account=account,
    )

    assert report.results[0].risk.approved is True
    assert report.results[0].fill is not None
    assert report.ending_cash == 1_000.0
    assert report.ending_positions == {"AAA": 10}


def test_engine_does_not_send_rejected_order_to_broker() -> None:
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(broker, RiskLimits(max_order_notional=500.0))
    account = AccountState(cash=2_000.0, positions={})

    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 10)],
        prices={"AAA": 100.0},
        account=account,
    )

    assert report.results[0].risk.approved is False
    assert report.results[0].fill is None
    assert broker.fills == []


def test_engine_executes_sells_before_buys_to_free_cash() -> None:
    broker = SimulationBroker({"AAA": 100.0, "BBB": 100.0})
    engine = ExecutionEngine(broker, RiskLimits(max_order_notional=10_000.0))
    account = AccountState(cash=0.0, positions={"AAA": 10})

    report = engine.execute(
        [
            OrderRequest("BBB", OrderSide.BUY, 10),
            OrderRequest("AAA", OrderSide.SELL, 10),
        ],
        prices={"AAA": 100.0, "BBB": 100.0},
        account=account,
    )

    assert [r.order.side for r in report.results] == [OrderSide.SELL, OrderSide.BUY]
    assert report.ending_cash == 0.0
    assert report.ending_positions == {"BBB": 10}


def test_engine_rejects_buy_when_cash_is_insufficient() -> None:
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(broker, RiskLimits(max_order_notional=10_000.0))
    account = AccountState(cash=500.0, positions={})

    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 10)],
        prices={"AAA": 100.0},
        account=account,
    )

    assert report.results[0].risk.approved is False
    assert report.results[0].risk.reason == "insufficient_cash"
    assert report.ending_cash == 500.0
    assert report.ending_positions == {}
    assert broker.fills == []
