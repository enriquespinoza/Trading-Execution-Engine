from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionEngine
from trading_execution_engine.models.portfolio import Position, TargetAllocation
from trading_execution_engine.reconciliation.rebalance import RebalanceConfig, build_rebalance_orders
from trading_execution_engine.risk.limits import RiskLimits


prices = {
    "SPY": 700.0,
    "QQQ": 620.0,
    "GLD": 330.0,
    "SCHD": 31.0,
}

portfolio_value = 100_000.0
positions = [
    Position("SPY", 20),
    Position("QQQ", 50),
    Position("GLD", 80),
    Position("SCHD", 200),
]
targets = [
    TargetAllocation("SPY", 0.18),
    TargetAllocation("QQQ", 0.40),
    TargetAllocation("GLD", 0.34),
    TargetAllocation("SCHD", 0.08),
]

orders = build_rebalance_orders(
    portfolio_value=portfolio_value,
    targets=targets,
    positions=positions,
    prices=prices,
    config=RebalanceConfig(min_trade_notional=100.0),
)

broker = SimulationBroker(prices)
engine = ExecutionEngine(
    broker,
    RiskLimits(max_order_notional=25_000.0, allow_short_sales=False),
)
results = engine.execute(
    orders,
    prices=prices,
    positions={p.symbol: p.quantity for p in positions},
)

print("DRY-RUN EXECUTION RESULTS")
print("=" * 80)
for result in results:
    fill = result.fill
    if fill is None:
        print(
            f"REJECTED {result.order.side.value:4} "
            f"{result.order.quantity:>5} {result.order.symbol:<5} "
            f"reason={result.risk.reason}"
        )
    else:
        print(
            f"FILLED   {fill.side.value:4} {fill.quantity:>5} {fill.symbol:<5} "
            f"@ ${fill.fill_price:,.2f} notional=${fill.notional:,.2f}"
        )
