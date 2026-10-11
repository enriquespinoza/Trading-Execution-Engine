from datetime import datetime, timedelta, timezone

from trading_execution_engine.approvals.service import (
    ApprovalService,
    ApprovalStatus,
)
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionControls, ExecutionEngine
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import (
    OrderRequest,
    OrderSide,
    OrderStatus,
)
from trading_execution_engine.notifications.base import NotificationResult
from trading_execution_engine.risk.limits import RiskLimits


class RecordingNotifier:
    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return NotificationResult(True, "sent", "SM-test")

    def send_approval_request(
        self,
        message,
        *,
        approve_command,
        reject_command,
    ):
        self.messages.append(
            message
            + "\n"
            + approve_command
            + "\n"
            + reject_command
        )
        return NotificationResult(True, "sent", "SM-test")


def build_service(tmp_path, *, now=None):
    notifier = RecordingNotifier()
    service = ApprovalService(
        store=JsonApprovalStore(tmp_path / "approvals.json"),
        notifier=notifier,
        authorized_phone_number="+15550002222",
        ttl_minutes=10,
        now=now,
        code_factory=lambda: "123456",
    )
    return service, notifier


def test_first_execution_requests_approval_and_does_not_submit(tmp_path):
    service, notifier = build_service(tmp_path)
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        order_id="trade-1",
    )
    account = AccountState(cash=1_000.0)

    report = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )

    result = report.results[0]
    assert result.status == OrderStatus.PENDING_APPROVAL
    assert result.execution_reason == "approval_requested"
    assert broker.fills == []
    assert "APPROVE 123456" in notifier.messages[0]


def test_approved_reply_allows_second_execution_attempt(tmp_path):
    service, _ = build_service(tmp_path)
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        order_id="trade-2",
    )
    account = AccountState(cash=1_000.0)

    first = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    assert first.results[0].status == OrderStatus.PENDING_APPROVAL

    decision = service.handle_reply(
        from_number="+15550002222",
        body="APPROVE 123456",
    )
    assert decision.status == ApprovalStatus.APPROVED

    second = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    assert second.results[0].status == OrderStatus.FILLED
    assert len(broker.fills) == 1
    assert account.positions["AAA"] == 1.0


def test_rejected_reply_prevents_submission(tmp_path):
    service, _ = build_service(tmp_path)
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        order_id="trade-3",
    )
    account = AccountState(cash=1_000.0)

    engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    service.handle_reply(
        from_number="+15550002222",
        body="REJECT 123456",
    )

    report = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    assert report.results[0].status == OrderStatus.REJECTED
    assert report.results[0].execution_reason == "human_rejected"
    assert broker.fills == []


def test_unauthorized_sender_cannot_approve(tmp_path):
    service, _ = build_service(tmp_path)
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        order_id="trade-4",
    )
    service.check_or_request(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )

    decision = service.handle_reply(
        from_number="+15559999999",
        body="APPROVE 123456",
    )
    assert decision.reason == "unauthorized_sender"

    state = service.check_or_request(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )
    assert state.status == ApprovalStatus.PENDING


def test_expired_approval_cannot_execute(tmp_path):
    current = [datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)]
    service, _ = build_service(
        tmp_path,
        now=lambda: current[0],
    )
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        1,
        order_id="trade-5",
    )
    service.check_or_request(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )

    current[0] += timedelta(minutes=11)
    reply = service.handle_reply(
        from_number="+15550002222",
        body="APPROVE 123456",
    )
    assert reply.status == ApprovalStatus.EXPIRED


def test_approval_does_not_bypass_fresh_cash_risk_check(tmp_path):
    service, _ = build_service(tmp_path)
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )
    order = OrderRequest(
        "AAA",
        OrderSide.BUY,
        5,
        order_id="trade-6",
    )
    account = AccountState(cash=1_000.0)

    engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    service.handle_reply(
        from_number="+15550002222",
        body="APPROVE 123456",
    )

    account.cash = 100.0
    report = engine.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    assert report.results[0].status == OrderStatus.REJECTED
    assert report.results[0].execution_reason == "insufficient_cash"
    assert broker.fills == []
