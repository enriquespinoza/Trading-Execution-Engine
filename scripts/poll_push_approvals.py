from datetime import datetime, timedelta, timezone

from trading_execution_engine.approvals.ntfy_responder import NtfyApprovalResponder
from trading_execution_engine.approvals.service import ApprovalService
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.notifications.ntfy_push import NtfyPushNotifier


notifier = NtfyPushNotifier.from_env()
service = ApprovalService(
    store=JsonApprovalStore("state/approvals.json"),
    notifier=notifier,
)
responder = NtfyApprovalResponder.from_env(service=service)

since = datetime.now(timezone.utc) - timedelta(minutes=30)
decisions = responder.poll_since(since)

if not decisions:
    print("No new approval responses.")
else:
    for decision in decisions:
        print(f"{decision.status.value}: {decision.reason}")
