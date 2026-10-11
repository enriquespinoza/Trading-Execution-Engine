from types import SimpleNamespace

from trading_execution_engine.brokers.simulation import SimulationBroker
from trading_execution_engine.engine import ExecutionControls, ExecutionEngine
from trading_execution_engine.models.account import AccountState
from trading_execution_engine.models.order import OrderRequest, OrderSide, OrderStatus
from trading_execution_engine.notifications.base import (
    NotificationResult,
    PreTradeAlert,
)
from trading_execution_engine.notifications.twilio_sms import TwilioSmsNotifier
from trading_execution_engine.risk.limits import RiskLimits


class RecordingNotifier:
    def __init__(self, events, *, sent=True):
        self.events = events
        self.sent = sent
        self.alerts = []

    def send(self, alert):
        self.events.append("notify")
        self.alerts.append(alert)
        return NotificationResult(
            sent=self.sent,
            reason="sent" if self.sent else "provider_failed",
        )


class RecordingBroker(SimulationBroker):
    def __init__(self, prices, events):
        super().__init__(prices)
        self.events = events

    def submit_order(self, order):
        self.events.append("submit")
        return super().submit_order(order)


def test_required_notification_without_notifier_fails_closed():
    broker = SimulationBroker({"AAA": 100.0})
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_notification=True),
    )
    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1)],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )

    assert report.results[0].status == OrderStatus.REJECTED
    assert (
        report.results[0].execution_reason
        == "pretrade_notifier_not_configured"
    )
    assert broker.fills == []


def test_notification_failure_prevents_broker_submission():
    events = []
    broker = RecordingBroker({"AAA": 100.0}, events)
    notifier = RecordingNotifier(events, sent=False)
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_notification=True),
        notifier=notifier,
    )

    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1)],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )

    assert events == ["notify"]
    assert report.results[0].status == OrderStatus.REJECTED
    assert report.results[0].execution_reason == "pretrade_notification_failed"
    assert broker.fills == []


def test_sms_alert_is_sent_before_broker_submission():
    events = []
    broker = RecordingBroker({"AAA": 100.0}, events)
    notifier = RecordingNotifier(events)
    engine = ExecutionEngine(
        broker,
        RiskLimits(max_order_notional=5_000.0),
        ExecutionControls(require_pretrade_notification=True),
        notifier=notifier,
    )

    report = engine.execute(
        [OrderRequest("AAA", OrderSide.BUY, 1, order_id="order-1")],
        prices={"AAA": 100.0},
        account=AccountState(cash=1_000.0),
    )

    assert events == ["notify", "submit"]
    assert report.results[0].status == OrderStatus.FILLED
    assert report.results[0].notification is not None
    assert report.results[0].notification.sent is True


def test_twilio_notifier_builds_pretrade_message_without_real_api_call():
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(sid="SM123")

    fake_client = SimpleNamespace(messages=FakeMessages())
    notifier = TwilioSmsNotifier(
        from_number="+15550001111",
        to_number="+15550002222",
        client=fake_client,
    )
    alert = PreTradeAlert(
        order=OrderRequest(
            "AAA",
            OrderSide.BUY,
            2,
            order_id="abc",
        ),
        estimated_fill_price=100.0,
        estimated_fees=1.0,
        available_cash=1_000.0,
    )

    result = notifier.send(alert)

    assert result.sent is True
    assert result.provider_message_id == "SM123"
    assert calls[0]["from_"] == "+15550001111"
    assert calls[0]["to"] == "+15550002222"
    assert "BUY 2 AAA" in calls[0]["body"]
    assert "order_id=abc" in calls[0]["body"]
