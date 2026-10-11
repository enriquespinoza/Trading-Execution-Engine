# Trading Execution Engine

A standalone execution layer that converts portfolio targets or strategy signals into controlled, auditable orders.

## Project boundary

This repository answers **how and whether to execute**. It does not decide which assets are attractive and it does not optimize portfolio weights.

Upstream systems:
- Stock Scanner Engine → candidate securities / ranked signals
- Portfolio Optimization Engine → target allocations
- Strategy research models → optional execution signals

This repository:
- reconciles target allocations against current positions;
- constructs proposed orders;
- applies pre-trade risk controls;
- maintains simulated cash and position state;
- sequences sells before buys during rebalances;
- routes approved orders to a broker adapter;
- records deterministic simulation results;
- reports post-trade target-weight drift;
- later supports paper-trading adapters before any live execution work.

## Phase 2 architecture

```text
Target Allocations + Current Account State + Prices
                        |
                        v
              Rebalance Reconciliation
                        |
                        v
                 Proposed Orders
                        |
                sells before buys
                        |
                        v
                    Risk Gates
           /               |               \
      reject       insufficient cash      approve
                                             |
                                             v
                                      Broker Interface
                                             |
                                             v
                                      SimulationBroker
                                             |
                                             v
                                  Cash + Positions Updated
                                             |
                                             v
                                  Post-Trade Reconciliation
```

## Safety boundary

No live-broker credentials and no live-order adapter are present. `SimulationBroker` remains the only implemented broker. Rejected orders never reach the broker adapter.

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
pytest
```

Run the deterministic dry simulation:

```bash
python scripts/run_dry_simulation.py
```

## Phase 2A implemented

- sell-before-buy rebalance sequencing;
- execution-time cash ledger;
- cash updates after every fill;
- position updates after every fill;
- insufficient-cash rejection;
- complete liquidation of positions omitted from target allocations;
- post-trade reconciliation of target vs. actual weights;
- whole-share execution policy retained from Phase 1;
- deterministic simulation only.

## Phase 2B implemented

- explicit fractional-share policy configuration;
- market and limit order representations;
- configurable slippage in basis points;
- per-order and per-share transaction-cost simulation;
- duplicate-order ID protection;
- market-session execution gate;
- global kill switch;
- broker order preview before risk approval.

## Phase 2 remaining

- persistent execution journal;
- durable idempotency across process restarts;
- portfolio snapshots and restart/recovery semantics.

## Later phases

**Phase 3 — state and auditability**
- execution journal
- portfolio state snapshots
- richer order lifecycle states
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
