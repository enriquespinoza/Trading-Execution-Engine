import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from trading_execution_engine.approvals.challenge import ApprovalSigner
from trading_execution_engine.approvals.ntfy_responder import NtfyApprovalResponder
from trading_execution_engine.approvals.service import ApprovalService
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.notifications.ntfy_push import NtfyPushNotifier


load_dotenv()

notifier = NtfyPushNotifier.from_env()
service = ApprovalService(
    store=JsonApprovalStore(
        os.environ.get(
            "TRADE_APPROVAL_STORE",
            "state/approvals.json",
        )
    ),
    notifier=notifier,
    signer=ApprovalSigner.from_env(),
    ttl_minutes=int(
        os.environ.get("TRADE_APPROVAL_TTL_MINUTES", "10")
    ),
)
responder = NtfyApprovalResponder.from_env(service=service)

since = datetime.now(timezone.utc) - timedelta(minutes=30)
decisions = responder.poll_since(since)

if not decisions:
    print("No new approval responses.")
else:
    for decision in decisions:
        print(f"{decision.status.value}: {decision.reason}")
