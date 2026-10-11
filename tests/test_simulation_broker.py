from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.models.order import OrderRequest, OrderSide


def test_simulation_broker_fills_at_configured_price() -> None:
    broker = SimulationBroker({"AAA": 123.45})
    fill = broker.submit_order(OrderRequest("aaa", OrderSide.BUY, 10))
    assert fill.symbol == "AAA"
    assert fill.fill_price == 123.45
    assert fill.quantity == 10
    assert fill.notional == 1234.5
