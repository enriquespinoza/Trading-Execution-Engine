from trading_execution_engine.notifications.ntfy_push import NtfyPushNotifier


notifier = NtfyPushNotifier.from_env()
result = notifier.send_message(
    "Trading Execution Engine push test."
)

if not result.sent:
    raise SystemExit(f"Push failed: {result.reason}")

print(
    "Push sent successfully"
    + (
        f" message_id={result.provider_message_id}"
        if result.provider_message_id
        else ""
    )
)
