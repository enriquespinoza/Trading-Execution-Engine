from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from trading_execution_engine.approvals.service import (
    ApprovalService,
    ApprovalStatus,
)
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import (
    ExecutionControls,
    ExecutionEngine,
)
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from trading_execution_engine.notifications.twilio_sms import (
    TwilioSmsNotifier,
)
from trading_execution_engine.risk.limits import RiskLimits


STATE_DIR = Path("state")
SCENARIO_PATH = STATE_DIR / "e2e_sms_scenario.json"
APPROVAL_PATH = STATE_DIR / "e2e_sms_approvals.json"

SYMBOL = "TEST"
PRICE = 100.0
QUANTITY = 2.0
STARTING_CASH = 1_000.0


def build_service() -> ApprovalService:
    load_dotenv()
    notifier = TwilioSmsNotifier.from_env()
    return ApprovalService(
        store=JsonApprovalStore(APPROVAL_PATH),
        notifier=notifier,
        authorized_phone_number=os.environ["TRADE_ALERT_TO_NUMBER"],
        ttl_minutes=int(
            os.environ.get("TRADE_APPROVAL_TTL_MINUTES", "10")
        ),
    )


def build_engine(service: ApprovalService) -> ExecutionEngine:
    broker = SimulationBroker({SYMBOL: PRICE})
    return ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )


def create_scenario() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    scenario = {
        "order_id": f"e2e-{uuid4()}",
        "symbol": SYMBOL,
        "side": OrderSide.BUY.value,
        "quantity": QUANTITY,
        "price": PRICE,
        "starting_cash": STARTING_CASH,
    }
    SCENARIO_PATH.write_text(
        json.dumps(scenario, indent=2),
        encoding="utf-8",
    )
    return scenario


def load_scenario() -> dict:
    if not SCENARIO_PATH.exists():
        raise SystemExit(
            "No E2E scenario exists. Run the 'request' command first."
        )
    return json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))


def make_order(scenario: dict) -> OrderRequest:
    return OrderRequest(
        scenario["symbol"],
        OrderSide(scenario["side"]),
        float(scenario["quantity"]),
        order_id=scenario["order_id"],
    )


def command_reset() -> None:
    for path in (SCENARIO_PATH, APPROVAL_PATH):
        if path.exists():
            path.unlink()
    print("E2E SMS approval state reset.")


def command_request() -> None:
    if SCENARIO_PATH.exists():
        scenario = load_scenario()
    else:
        scenario = create_scenario()

    service = build_service()
    engine = build_engine(service)
    account = AccountState(cash=float(scenario["starting_cash"]))
    order = make_order(scenario)

    report = engine.execute(
        [order],
        prices={scenario["symbol"]: float(scenario["price"])},
        account=account,
    )
    result = report.results[0]

    print("E2E SMS APPROVAL — REQUEST")
    print("=" * 72)
    print(f"Order ID:   {order.order_id}")
    print(
        f"Order:      {order.side.value} {order.quantity:g} "
        f"{order.symbol} @ simulated ${scenario['price']:,.2f}"
    )
    print(f"Status:     {result.status.value}")
    print(f"Reason:     {result.execution_reason}")
    print(f"Broker fill:{' YES' if result.fill else ' NO'}")

    if result.status == OrderStatus.PENDING_APPROVAL:
        print("\nSMS approval request sent.")
        print("Reply from the authorized phone with the command shown in the SMS.")
        print("The SimulationBroker has NOT received the trade.")
    elif result.status == OrderStatus.FILLED:
        raise SystemExit(
            "Unexpected fill during request stage; approval gate failed closed."
        )


def command_status() -> None:
    scenario = load_scenario()
    store = JsonApprovalStore(APPROVAL_PATH)
    record = store.get(scenario["order_id"])

    print("E2E SMS APPROVAL — STATUS")
    print("=" * 72)
    print(f"Order ID: {scenario['order_id']}")
    if record is None:
        print("Approval: no approval record exists")
        return

    print(f"Approval: {record.status}")
    print(f"Created:  {record.created_at}")
    print(f"Expires:  {record.expires_at}")
    if record.resolved_at:
        print(f"Resolved: {record.resolved_at}")


def command_execute() -> None:
    scenario = load_scenario()
    service = build_service()
    engine = build_engine(service)
    account = AccountState(cash=float(scenario["starting_cash"]))
    order = make_order(scenario)

    report = engine.execute(
        [order],
        prices={scenario["symbol"]: float(scenario["price"])},
        account=account,
    )
    result = report.results[0]

    print("E2E SMS APPROVAL — EXECUTE")
    print("=" * 72)
    print(f"Order ID:    {order.order_id}")
    print(f"Status:      {result.status.value}")
    print(f"Reason:      {result.execution_reason}")
    print(f"Ending cash: ${report.ending_cash:,.2f}")
    print(f"Positions:   {dict(report.ending_positions)}")

    if result.status == OrderStatus.FILLED:
        print("\nPASS: human approval was recorded and SimulationBroker filled the order.")
    elif result.status == OrderStatus.PENDING_APPROVAL:
        print("\nNo trade made: approval is still pending.")
    elif result.status == OrderStatus.REJECTED:
        print("\nNo trade made: execution was rejected.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end Twilio SMS approval simulation."
    )
    parser.add_argument(
        "command",
        choices=("reset", "request", "status", "execute"),
    )
    args = parser.parse_args()

    commands = {
        "reset": command_reset,
        "request": command_request,
        "status": command_status,
        "execute": command_execute,
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
