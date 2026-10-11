from trading_execution_engine.models.order import OrderRequest, OrderSide
from trading_execution_engine.notifications.base import PreTradeAlert
from trading_execution_engine.notifications.twilio_sms import TwilioSmsNotifier


notifier = TwilioSmsNotifier.from_env()
alert = PreTradeAlert(
    order=OrderRequest(
        "TEST",
        OrderSide.BUY,
        1,
        order_id="sms-smoke-test",
    ),
    estimated_fill_price=100.0,
    estimated_fees=0.0,
    available_cash=1_000.0,
)
result = notifier.send(alert)

if not result.sent:
    raise SystemExit(f"SMS failed: {result.reason}")

print(
    "SMS sent successfully"
    + (
        f" message_id={result.provider_message_id}"
        if result.provider_message_id
        else ""
    )
)
