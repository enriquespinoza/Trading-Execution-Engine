from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionEngine
from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.risk.limits import RiskLimits


def test_engine_executes_approved_order() -> None:
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(broker, RiskLimits(max_order_notional=5_000.0))
    results = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 10)],
        prices={"AAA": 100.0},
        positions={"AAA": 0},
    )
    assert results[0].risk.approved is True
    assert results[0].fill is not None


def test_engine_does_not_send_rejected_order_to_broker() -> None:
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(broker, RiskLimits(max_order_notional=500.0))
    results = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 10)],
        prices={"AAA": 100.0},
        positions={"AAA": 0},
    )
    assert results[0].risk.approved is False
    assert results[0].fill is None
    assert broker.fills == []
