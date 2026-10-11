import json
from datetime import datetime, timezone
from types import SimpleNamespace

import trading_execution_engine.approvals.ntfy_responder as responder_module
import trading_execution_engine.notifications.ntfy_push as push_module
from trading_execution_engine.approvals.challenge import ApprovalSigner
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


def make_notifier():
    return NtfyPushNotifier(
        base_url="https://ntfy.sh",
        alert_topic="alerts-abc",
        response_topic="responses-def",
        alert_publish_token="alert-token",
        response_publish_token="response-write-token",
    )


def test_ntfy_push_builds_signed_actions_and_auth_headers(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        return FakeResponse(b'{"id":"msg123"}')

    monkeypatch.setattr(push_module.urllib.request, "urlopen", fake_urlopen)

    notifier = make_notifier()
    result = notifier.send_approval_request(
        "Approve this trade",
        approve_command="APPROVE signed-token",
        reject_command="REJECT signed-token",
    )

    assert result.sent is True
    assert result.provider_message_id == "msg123"
    assert captured["authorization"] == "Bearer alert-token"
    actions = captured["payload"]["actions"]
    assert actions[0]["label"] == "Approve"
    assert actions[0]["body"] == "APPROVE signed-token"
    assert (
        actions[0]["headers"]["Authorization"]
        == "Bearer response-write-token"
    )
    assert actions[1]["label"] == "Reject"
    assert actions[1]["body"] == "REJECT signed-token"


def test_ntfy_response_poll_updates_signed_approval(monkeypatch, tmp_path):
    notifier = make_notifier()
    signer = ApprovalSigner("s" * 32)
    service = ApprovalService(
        store=JsonApprovalStore(tmp_path / "approvals.json"),
        notifier=notifier,
        signer=signer,
        ttl_minutes=10,
        code_factory=lambda: "nonce-123",
    )

    captured = {}

    def fake_send(message, *, approve_command, reject_command):
        captured["approve_command"] = approve_command
        return SimpleNamespace(
            sent=True,
            reason="sent",
            provider_message_id="x",
        )

    monkeypatch.setattr(
        notifier,
        "send_approval_request",
        fake_send,
    )

    order = OrderRequest("AAA", OrderSide.BUY, 1, order_id="order-1")
    pending = service.check_or_request(
        order=order,
        estimated_fill_price=100.0,
        estimated_fees=0.0,
    )
    assert pending.status == ApprovalStatus.PENDING

    payload = (
        json.dumps(
            {
                "event": "message",
                "message": captured["approve_command"],
            }
        )
        + "\n"
    ).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert (
            request.headers["Authorization"]
            == "Bearer response-read-token"
        )
        return FakeResponse(payload)

    monkeypatch.setattr(
        responder_module.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    responder = NtfyApprovalResponder(
        service=service,
        base_url="https://ntfy.sh",
        response_topic="responses-def",
        response_read_token="response-read-token",
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
