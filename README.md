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


## Phase 2E — push approval on phone

The primary human-approval path now uses **ntfy push notifications** instead
of SMS. Twilio remains optional fallback code.

The push workflow is:

```text
Proposed trade
    |
    v
fresh preview + risk
    |
    v
ntfy push to phone
    |
    +-- Approve button
    |      |
    |      v
    |  response topic
    |
    +-- Reject button
           |
           v
       response topic
              |
              v
      local approval poller
              |
              v
       durable approval state
              |
              v
       next execution pass
              |
              v
      fresh preview + risk
              |
              v
        SimulationBroker
```

No inbound webhook or public tunnel is required for this path.

### Phone setup

Install the ntfy app on the phone and subscribe to the alert topic configured
in `NTFY_ALERT_TOPIC`.

For initial testing, configure two long random topic names:

```text
NTFY_BASE_URL=https://ntfy.sh
NTFY_ALERT_TOPIC=<long-random-alert-topic>
NTFY_RESPONSE_TOPIC=<different-long-random-response-topic>
NTFY_ACCESS_TOKEN=
```

Do not use human-readable public topic names for real trading alerts. For
production use, prefer authenticated private topics or a self-hosted ntfy
instance.

### Push smoke test

```bash
python scripts/send_test_push.py
```

Your phone should receive:

```text
Trading Execution Engine push test.
```

### Approval response polling

Approval action buttons publish `APPROVE <token>` or `REJECT <token>` to
the private response topic. Pull those responses into the durable approval
store with:

```bash
python scripts/poll_push_approvals.py
```

The response poller does not place a trade. It only updates approval state.
The next execution pass still performs fresh preview and risk checks.

The SMS/Twilio path can remain installed as an optional adapter, but it is no
longer the recommended development path.


## Phase 2F — hardened signed push approvals

The ntfy approval transport is treated as **untrusted transport**. An approval
message is not trusted merely because it came from the response topic.

Each approval challenge now includes:

- a cryptographically random nonce;
- the exact order ID;
- symbol;
- BUY/SELL side;
- quantity;
- order type;
- limit price when present;
- estimated execution price;
- estimated fees;
- expiration time;
- SHA-256 trade fingerprint;
- HMAC-SHA256 signature.

The signing key remains local in:

```text
TRADE_APPROVAL_SIGNING_KEY
```

and is never included in the notification or committed to Git.

### Single-use lifecycle

```text
PENDING
   |
   +-- invalid signature --> remain PENDING / reject command
   +-- expired -----------> EXPIRED
   +-- REJECT ------------> REJECTED
   +-- APPROVE -----------> APPROVED
                              |
                              v
                     exact trade re-check
                              |
                    +---------+---------+
                    |                   |
                 changed              exact
                    |                   |
                    v                   v
                REJECTED            CONSUMED
                                        |
                                        v
                               broker.submit_order()
```

An approval is marked `CONSUMED` **before** broker submission. This is
intentional: if broker submission fails or the process crashes after
consumption, the same approval cannot be replayed. A new approval is required.

The durable JSON approval store therefore provides replay protection across
process restarts, not only within one Python process.

### Least-privilege ntfy credentials

Use separate ntfy identities/tokens rather than one shared credential:

```text
NTFY_ALERT_PUBLISH_TOKEN
    WRITE only -> alert topic

Phone ntfy identity
    READ only  -> alert topic

NTFY_RESPONSE_PUBLISH_TOKEN
    WRITE only -> response topic

NTFY_RESPONSE_READ_TOKEN
    READ only  -> response topic
```

The Approve/Reject action button includes only the **response write token**,
which should have no read access and no access to the alert topic.

ntfy's HTTP action buttons support custom HTTP headers, so the response action
can authenticate to the response topic without exposing the response-reader
credential.

### Signed approval configuration

Generate the local HMAC key on your machine:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store the output only in local `.env`:

```text
TRADE_APPROVAL_SIGNING_KEY=<generated secret>
```

Do not send the signing key to ntfy, GitHub, or ChatGPT.

### Security boundary

This architecture protects against:

- blind response-topic spoofing;
- command tampering;
- changing APPROVE to REJECT or vice versa;
- changing order parameters after approval;
- expired approvals;
- replay of an already consumed approval;
- replay after an execution-engine restart.

It does **not** protect against a fully compromised phone, a compromised
authenticated alert-topic reader, or compromise of the local signing key.
Those remain outside the transport-spoofing threat model.

For future live trading, consider a dedicated approval app/WebAuthn or a
self-hosted ntfy deployment with network-level access controls in addition to
these application-level protections.


## Phase 2G — scanner allocation → execution-safe target

`candidate_allocation.csv` is never consumed directly by the order engine.

The execution repository first converts the scanner allocation into a frozen
handoff artifact:

```text
candidate_allocation.csv
        |
        | SHA-256
        v
allocation provenance
        |
reference_prices.csv
current_positions.csv
portfolio capital
execution state
        |
        v
execution_target.csv
        |
        +--> execution_target.manifest.json
        |
        v
future order construction
```

The target CSV contract is exactly:

```text
allocation_sha256
symbol
approved_target_weight
reference_price
portfolio_capital
target_dollar_value
target_shares
current_position
share_delta
execution_state
```

Only `DRY_RUN` and `PAPER` are valid execution states. There is no
`LIVE` state in the handoff contract.

### Scanner allocation input

The current scanner allocation contract requires:

```text
scanner_rank
symbol
scanner_score
annualized_volatility
target_weight
```

The execution engine uses only the rank, symbol, and approved target weight.
The scanner score and volatility remain upstream research fields.

Target weights must sum to 1 within a tolerance of 1e-6.

### Reference-price input

```csv
symbol,reference_price
SPY,700.00
QQQ,620.00
```

Every allocation symbol and every currently held symbol must have a positive
reference price.

### Current-position input

```csv
symbol,current_position
SPY,20
QQQ,50
```

Positions are whole, non-negative shares in this contract.

A currently held symbol that is absent from `candidate_allocation.csv` is
written to the execution target with:

```text
approved_target_weight = 0
target_dollar_value     = 0
target_shares           = 0
share_delta             = -current_position
```

That makes liquidation intent explicit instead of silently dropping the
position.

### Target-share calculation

```text
target_dollar_value = portfolio_capital * approved_target_weight
target_shares       = floor(target_dollar_value / reference_price)
share_delta         = target_shares - current_position
```

Whole-share flooring is deterministic and matches the current execution
policy.

### Build command

Example:

```bash
python scripts/build_execution_target.py \
  --allocation /path/to/candidate_allocation.csv \
  --prices /path/to/reference_prices.csv \
  --positions /path/to/current_positions.csv \
  --capital 100000 \
  --state DRY_RUN \
  --output reports/execution/2026-10-16/execution_target.csv
```

For a scanner artifact already validated elsewhere, pin its expected SHA:

```bash
python scripts/build_execution_target.py \
  --allocation /path/to/candidate_allocation.csv \
  --prices /path/to/reference_prices.csv \
  --positions /path/to/current_positions.csv \
  --capital 100000 \
  --state PAPER \
  --expected-allocation-sha256 <known-sha256> \
  --output reports/execution/2026-10-16/execution_target.csv
```

A SHA mismatch fails closed.

### Manifest

The companion manifest records:

- execution-target contract version;
- generation timestamp;
- allocation SHA-256;
- reference-price file SHA-256;
- current-position file SHA-256;
- output execution-target SHA-256;
- portfolio capital;
- row count;
- execution state;
- whole-share policy;
- `live_execution_allowed: false`.

This artifact is the intended boundary between allocation research and order
construction.
