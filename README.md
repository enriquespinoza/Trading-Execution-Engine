# Trading Execution Engine

A standalone execution layer that converts portfolio targets or strategy signals into controlled, auditable orders.

## Project boundary

This repository answers **how and whether to execute**. It does not decide which assets are attractive and it does not optimize portfolio weights.

Upstream systems:
- Stock Scanner Engine → candidate securities / ranked signals
- Portfolio Optimization Engine → target allocations
- Strategy research models (for example TMF research) → optional execution signals

This repository:
- reconciles target allocations against current positions;
- constructs proposed orders;
- applies pre-trade risk controls;
- routes approved orders to a broker adapter;
- records deterministic simulation results;
- later supports paper-trading adapters before any live execution work.

## Phase 1 architecture

```text
Target Allocations + Current Positions + Prices
                    |
                    v
          Rebalance / Reconciliation
                    |
                    v
             Proposed Orders
                    |
                    v
               Risk Gates
              /          \
         reject         approve
                           |
                           v
                    Broker Interface
                           |
                           v
                    SimulationBroker
```

## Safety boundary

Phase 1 contains no live-broker credentials and no live-order adapter. `SimulationBroker` is the only implemented broker.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
```

Run the deterministic dry simulation:

```bash
python scripts/run_dry_simulation.py
```

## Phase 1 completion criteria

- Rebalance calculations are deterministic and unit-tested.
- Risk gates can block invalid or oversized orders.
- Simulation broker is the only order destination.
- Rejected orders never reach the broker.
- The engine can accept target weights from the Portfolio Optimization Engine without importing that project.
- Tests pass locally before the next phase begins.

## Planned phases

**Phase 2 — execution semantics**
- cash-aware sequencing
- sell-before-buy rebalance ordering
- fractional-share policy
- limit-order representation
- configurable slippage and transaction costs
- idempotency / duplicate-order prevention
- trading-session rules

**Phase 3 — state and auditability**
- execution journal
- portfolio state snapshots
- order lifecycle states
- reconciliation after fills
- restart / recovery behavior

**Phase 4 — paper-trading adapter**
- broker authentication isolated from strategy logic
- read-only account/position verification first
- order preview / validation
- paper account only
- cancellation and rejected-order handling

**Phase 5 — orchestrator integration**
- consume versioned target-allocation artifacts from the Portfolio Optimization Engine
- consume optional signal artifacts from research/scanner projects
- emit versioned execution reports back to the top-level orchestrator

No live trading should be enabled until the project has passed deterministic simulations and a sustained paper-trading validation period.
