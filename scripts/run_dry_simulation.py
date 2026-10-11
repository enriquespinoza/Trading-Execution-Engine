from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionEngine
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.portfolio import Position, TargetAllocation
from trading_execution_engine.reconciliation.rebalance import (
    RebalanceConfig,
    build_rebalance_orders,
    reconcile_portfolio,
)
from trading_execution_engine.risk.limits import RiskLimits


prices = {
    "SPY": 700.0,
    "QQQ": 620.0,
    "GLD": 330.0,
    "SCHD": 31.0,
}

starting_cash = 22_400.0
positions = [
    Position("SPY", 20),
    Position("QQQ", 50),
    Position("GLD", 80),
    Position("SCHD", 200),
]
portfolio_value = starting_cash + sum(
    position.quantity * prices[position.symbol] for position in positions
)

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

account = AccountState.from_mapping(
    cash=starting_cash,
    positions={p.symbol: p.quantity for p in positions},
)
broker = SimulationBroker(prices)
engine = ExecutionEngine(
    broker,
    RiskLimits(max_order_notional=25_000.0, allow_short_sales=False),
)
report = engine.execute(orders, prices=prices, account=account)

print("DRY-RUN EXECUTION RESULTS")
print("=" * 88)
print(f"Starting cash: ${report.starting_cash:,.2f}")
for result in report.results:
    fill = result.fill
    if fill is None:
        print(
            f"REJECTED {result.order.side.value:4} "
            f"{result.order.quantity:>5} {result.order.symbol:<5} "
            f"reason={result.risk.reason:<30} cash=${result.cash_after:,.2f}"
        )
    else:
        print(
            f"FILLED   {fill.side.value:4} {fill.quantity:>5} {fill.symbol:<5} "
            f"@ ${fill.fill_price:,.2f} notional=${fill.notional:,.2f} "
            f"cash=${result.cash_after:,.2f}"
        )

print("-" * 88)
print(f"Ending cash:   ${report.ending_cash:,.2f}")
print(f"Positions:     {dict(report.ending_positions)}")

reconciliation = reconcile_portfolio(
    targets=targets,
    positions=report.ending_positions,
    cash=report.ending_cash,
    prices=prices,
)

print("\nPOST-TRADE RECONCILIATION")
print("=" * 88)
for line in reconciliation.lines:
    print(
        f"{line.symbol:<5} qty={line.quantity:>5} "
        f"target={line.target_weight:>7.2%} "
        f"actual={line.actual_weight:>7.2%} "
        f"drift={line.weight_drift:>+8.2%}"
    )
print(f"CASH  target=  0.00% actual={reconciliation.cash_weight:>7.2%}")
