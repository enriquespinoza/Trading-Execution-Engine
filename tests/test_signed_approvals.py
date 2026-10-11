from datetime import datetime, timezone

from trading_execution_engine.approvals.challenge import ApprovalSigner
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


class CapturingNotifier:
    def __init__(self):
        self.approve_command = None
        self.reject_command = None

    def send_message(self, message):
        return NotificationResult(True, "sent", "msg")

    def send_approval_request(
        self,
        message,
        *,
        approve_command,
        reject_command,
    ):
        self.approve_command = approve_command
        self.reject_command = reject_command
        return NotificationResult(True, "sent", "msg")


def build_secure_service(tmp_path):
    notifier = CapturingNotifier()
    signer = ApprovalSigner("k" * 32)
    service = ApprovalService(
        store=JsonApprovalStore(tmp_path / "approvals.json"),
        notifier=notifier,
        signer=signer,
        ttl_minutes=10,
        code_factory=lambda: "nonce-secure-1",
    )
    return service, notifier


def request_trade(service, order):
    return service.check_or_request(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )


def test_valid_signed_approval_is_accepted(tmp_path):
    service, notifier = build_secure_service(tmp_path)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="signed-1")
    request_trade(service, order)

    decision = service.handle_command(notifier.approve_command)

    assert decision.status == ApprovalStatus.APPROVED


def test_tampered_signature_is_rejected_and_state_stays_pending(tmp_path):
    service, notifier = build_secure_service(tmp_path)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="signed-2")
    request_trade(service, order)

    command = notifier.approve_command
    tampered = command[:-1] + ("A" if command[-1] != "A" else "B")
    decision = service.handle_command(tampered)

    assert decision.status == ApprovalStatus.REJECTED
    assert decision.reason == "invalid_approval_signature"
    assert (
        service.check_or_request(
            order=order,
            estimated_fill_price=100.0,
            estimated_fees=0.0,
        ).status
        == ApprovalStatus.PENDING
    )


def test_action_substitution_invalidates_signature(tmp_path):
    service, notifier = build_secure_service(tmp_path)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="signed-3")
    request_trade(service, order)

    forged = notifier.approve_command.replace(
        "APPROVE ",
        "REJECT ",
        1,
    )
    decision = service.handle_command(forged)

    assert decision.status == ApprovalStatus.REJECTED
    assert decision.reason == "invalid_approval_signature"


def test_approved_trade_change_is_rejected(tmp_path):
    service, notifier = build_secure_service(tmp_path)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="signed-4")
    request_trade(service, order)
    service.handle_command(notifier.approve_command)

    changed = service.check_or_request(
        order=order,
        estimated_fill_price=101.0,
        estimated_fees=0.0,
    )

    assert changed.status == ApprovalStatus.REJECTED
    assert changed.reason == "approved_trade_changed"


def test_approval_is_consumed_once_before_submission(tmp_path):
    service, notifier = build_secure_service(tmp_path)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="signed-5")
    request_trade(service, order)
    service.handle_command(notifier.approve_command)

    first = service.consume_approval(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )
    second = service.consume_approval(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )

    assert first.status == ApprovalStatus.CONSUMED
    assert first.reason == "approval_consumed"
    assert second.status == ApprovalStatus.CONSUMED
    assert second.reason == "approval_consumed"


def test_consumed_approval_cannot_replay_after_engine_restart(tmp_path):
    service, notifier = build_secure_service(tmp_path)
    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="signed-6")
    account = AccountState(cash=1_000.0)
    broker = SimulationBroker({"AAA": 100.0})

    engine_one = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )

    first = engine_one.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    assert first.results[0].status == OrderStatus.PENDING_APPROVAL

    service.handle_command(notifier.approve_command)

    second = engine_one.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )
    assert second.results[0].status == OrderStatus.FILLED

    # Simulate a process restart: in-memory duplicate-order state is gone,
    # but durable approval state remains CONSUMED.
    engine_two = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_approval=True),
        approval_service=service,
    )
    replay = engine_two.execute(
        [order],
        prices={"AAA": 100.0},
        account=account,
    )

    assert replay.results[0].status == OrderStatus.REJECTED
    assert replay.results[0].execution_reason == "approval_consumed"
    assert len(broker.fills) == 1
