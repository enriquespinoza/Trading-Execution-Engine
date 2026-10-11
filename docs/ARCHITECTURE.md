# Architecture

## Separation of responsibilities

### Scanner
Answers: **What should be considered?**

### Optimizer
Answers: **What should the portfolio own and at what target weights?**

### Execution engine
Answers: **What trades are required, are they permitted, and how should they be routed?**

## Phase 2 data flow

```text
Optimizer target artifact
        |
        v
TargetAllocation[]
        |
        +--------------------+
        |                    |
        v                    v
Current positions       Current cash
        |                    |
        +----------+---------+
                   |
                   v
          build_rebalance_orders
                   |
                   v
          proposed BUY / SELL orders
                   |
                   v
          deterministic sequencing
          SELL orders before BUY orders
                   |
                   v
             pre-trade risk
                   |
                   v
             SimulationBroker
                   |
                   v
          AccountState.apply_fill
             /             \
         cash update     position update
                   |
                   v
          reconcile_portfolio
                   |
                   v
        actual weights + drift
```

## Optimizer-compatible target input

A later integration layer will validate a versioned artifact similar to:

```json
{
  "portfolio_date": "2026-11-02",
  "targets": {
    "SPY": 0.18,
    "QQQ": 0.40,
    "GLD": 0.34,
    "SCHD": 0.08
  }
}
```

The execution engine must not import optimizer internals. The repository boundary is a versioned data contract so either project can be frozen, tested, or replaced independently.

## Account state

Phase 2 introduces execution-time account state:

```text
AccountState
├── cash
└── positions
    ├── SPY -> quantity
    ├── QQQ -> quantity
    └── ...
```

Each approved simulated fill is applied immediately. SELL fills increase cash before subsequent BUY orders are evaluated. BUY fills reduce cash and are rejected before broker submission if purchasing cash is insufficient.

## Rebalance semantics

1. Build the complete order set from target weights and current positions.
2. A current holding absent from targets is interpreted as a target weight of zero and is eligible for full liquidation.
3. Execute SELL orders first.
4. Update cash and positions after each fill.
5. Evaluate BUY orders against the newly available cash balance.
6. Produce final cash, positions, and target-weight drift.

## Core invariants

- A proposed order must never reach a broker adapter before passing pre-trade risk checks.
- A BUY must not create negative cash in Phase 2.
- A SELL must not create a short position while short sales are disabled.
- Execution order is deterministic: sells precede buys.
- `SimulationBroker` is the only broker implementation until paper-trading work begins.
