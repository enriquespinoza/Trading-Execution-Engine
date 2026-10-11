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


## Phase 2C — pre-trade phone alerts

The execution engine can require a successful phone notification before an
otherwise-approved order is submitted to the broker.

The order path becomes:

```text
Proposed order
    |
    v
Execution controls
    |
    v
Broker preview
    |
    v
Risk approval
    |
    v
Pre-trade SMS required?
    |
    +-- SMS fails / notifier missing --> REJECT ORDER
    |
    +-- SMS sent successfully
                |
                v
         Broker submission
```

The notification contains the side, quantity, symbol, order type, estimated
fill price, estimated notional, estimated fees, and order ID.

No Twilio credentials or phone numbers belong in Git. Configure them through
environment variables using `.env.example` as the field reference.

Install SMS support:

```bash
python -m pip install -e ".[dev,sms]"
```

Required Twilio configuration:

```text
TWILIO_ACCOUNT_SID
TWILIO_FROM_NUMBER
TRADE_ALERT_TO_NUMBER
```

For authentication, configure either:

```text
TWILIO_API_KEY
TWILIO_API_SECRET
```

or:

```text
TWILIO_AUTH_TOKEN
```

Before enabling the gate in any paper-trading adapter, send a smoke-test SMS:

```bash
python scripts/send_test_sms.py
```

For an execution engine that must fail closed when phone notification is not
available:

```python
from trading_execution_engine.engine import ExecutionControls
from trading_execution_engine.notifications.twilio_sms import TwilioSmsNotifier

controls = ExecutionControls(
    require_pretrade_notification=True,
)
notifier = TwilioSmsNotifier.from_env()
```

A successfully sent SMS is currently a **notification gate**, not a human
approval gate. A later approval workflow can require an explicit YES/APPROVE
response before broker submission.


## Phase 2D — human-in-the-loop SMS approval

Phone notification can now be upgraded to a mandatory approval workflow.

```text
Order proposed
    |
    v
controls + broker preview + risk
    |
    v
SMS approval request
    |
    v
PENDING_APPROVAL
    |
    +-- REJECT <code>  --> REJECTED
    |
    +-- expires        --> REJECTED
    |
    +-- APPROVE <code>
             |
             v
   next execution pass
             |
             v
   fresh preview + fresh risk
             |
             v
      broker submission
```

The engine never blocks waiting for a text message. The first pass records a
durable pending approval in `state/approvals.json` and does not submit an
order. An authenticated inbound Twilio webhook records the phone reply. A
subsequent execution pass must observe `APPROVED` and still pass fresh
market and account checks before broker submission.

Enable the gate in code with:

```python
from trading_execution_engine.approvals.service import ApprovalService
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.engine import ExecutionControls
from trading_execution_engine.notifications.twilio_sms import TwilioSmsNotifier

notifier = TwilioSmsNotifier.from_env()
approval_service = ApprovalService(
    store=JsonApprovalStore("state/approvals.json"),
    notifier=notifier,
    authorized_phone_number=os.environ["TRADE_ALERT_TO_NUMBER"],
    ttl_minutes=10,
)

controls = ExecutionControls(
    require_pretrade_approval=True,
)
```

Run the local approval webhook:

```bash
python scripts/run_approval_webhook.py
```

Twilio must be able to reach the webhook over a public HTTPS URL. For local
development, expose port 5000 with a development tunnel and configure the
Twilio phone number's incoming-message webhook as:

```text
https://YOUR-PUBLIC-HOST/sms/approval
```

Set that exact URL in `TWILIO_APPROVAL_WEBHOOK_URL`. Exact URL matching is
important because the inbound request signature is validated before any
approval command is accepted.

Valid replies are:

```text
APPROVE 123456
REJECT 123456
```

Only `TRADE_ALERT_TO_NUMBER` is authorized to resolve approvals. Approval
codes expire after `TRADE_APPROVAL_TTL_MINUTES`, default 10 minutes.


## End-to-end Twilio approval simulation

This test exercises the real SMS path while keeping order execution entirely
inside `SimulationBroker`.

### 1. Configure Twilio

Use an SMS-capable Twilio phone number. In the Twilio Console for that number,
set **Messaging → A message comes in** to **Webhook**, use **HTTP POST**, and
point it to:

```text
https://YOUR-PUBLIC-HOST/sms/approval
```

The webhook must be publicly reachable. For development, a temporary HTTPS
tunnel to local port 5000 is sufficient.

Set the exact same public URL in:

```text
TWILIO_APPROVAL_WEBHOOK_URL=https://YOUR-PUBLIC-HOST/sms/approval
```

The exact URL matters because Twilio request signatures include the webhook
URL.

### 2. Start the local webhook

```bash
python scripts/run_approval_webhook.py
```

Leave that terminal running.

### 3. Reset prior E2E state

In a second terminal:

```bash
python scripts/run_e2e_sms_approval_simulation.py reset
```

### 4. Generate the simulated trade

```bash
python scripts/run_e2e_sms_approval_simulation.py request
```

Expected state:

```text
Status:     PENDING_APPROVAL
Broker fill: NO
```

Your real phone should receive an SMS similar to:

```text
TRADE APPROVAL REQUIRED
BUY 2 TEST
MARKET est price $100.00
Notional $200.00 | fees $0.00
Reply APPROVE 123456 or REJECT 123456
Expires in 10 min.
```

### 5. Approve from the authorized phone

Reply to the Twilio number using the exact command from the SMS:

```text
APPROVE 123456
```

The inbound webhook only records the approval. It does not submit a trade.

Check the durable state:

```bash
python scripts/run_e2e_sms_approval_simulation.py status
```

Expected:

```text
Approval: APPROVED
```

### 6. Re-run execution

```bash
python scripts/run_e2e_sms_approval_simulation.py execute
```

The engine performs a fresh preview and risk check before the simulated fill.
Expected ending state:

```text
Status:      FILLED
Ending cash: $800.00
Positions:   {'TEST': 2.0}

PASS: human approval was recorded and SimulationBroker filled the order.
```

No brokerage API is called anywhere in this E2E test.
