import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import trading_execution_engine.approvals.ntfy_responder as responder_module
import trading_execution_engine.notifications.ntfy_push as push_module
from trading_execution_engine.approvals.ntfy_responder import NtfyApprovalResponder
from trading_execution_engine.approvals.service import ApprovalService, ApprovalStatus
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.notifications.ntfy_push import NtfyPushNotifier


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_ntfy_push_builds_approve_and_reject_actions(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(b'{"id":"msg123"}')

    monkeypatch.setattr(push_module.urllib.request, "urlopen", fake_urlopen)

    notifier = NtfyPushNotifier(
        base_url="https://ntfy.sh",
        alert_topic="alerts-abc",
        response_topic="responses-def",
    )
    result = notifier.send_approval_request(
        "Approve this trade",
        approval_code="secret-code",
    )

    assert result.sent is True
    assert result.provider_message_id == "msg123"
    actions = captured["payload"]["actions"]
    assert actions[0]["label"] == "Approve"
    assert actions[0]["body"] == "APPROVE secret-code"
    assert actions[1]["label"] == "Reject"
    assert actions[1]["body"] == "REJECT secret-code"


def test_ntfy_response_poll_updates_approval(monkeypatch, tmp_path):
    notifier = NtfyPushNotifier(
        base_url="https://ntfy.sh",
        alert_topic="alerts-abc",
        response_topic="responses-def",
    )
    service = ApprovalService(
        store=JsonApprovalStore(tmp_path / "approvals.json"),
        notifier=notifier,
        ttl_minutes=10,
        code_factory=lambda: "code-123",
    )

    monkeypatch.setattr(
        notifier,
        "send_approval_request",
        lambda *args, **kwargs: SimpleNamespace(
            sent=True,
            reason="sent",
            provider_message_id="x",
        ),
    )

    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="order-1")
    pending = service.check_or_request(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )
    assert pending.status == ApprovalStatus.PENDING

    payload = (
        json.dumps({"event":"message","message":"APPROVE code-123"}) + "\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout):
        return FakeResponse(payload)

    monkeypatch.setattr(responder_module.urllib.request, "urlopen", fake_urlopen)

    responder = NtfyApprovalResponder(
        service=service,
        base_url="https://ntfy.sh",
        response_topic="responses-def",
    )
    decisions = responder.poll_since(datetime.now(timezone.utc))

    assert decisions[0].status == ApprovalStatus.APPROVED
    assert (
        service.check_or_request(
            order=order,
            estimated_fill_price=100.0,
            estimated_fees=0.0,
        ).status
        == ApprovalStatus.APPROVED
    )
