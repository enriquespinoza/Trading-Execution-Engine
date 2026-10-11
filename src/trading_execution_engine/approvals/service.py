from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable

from trading_execution_engine.approvals.store import (
    ApprovalRecord,
    JsonApprovalStore,
)
from trading_execution_engine.models.order import OrderRequest
from trading_execution_engine.notifications.base import (
    NotificationResult,
    TradeNotifier,
)


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ApprovalDecision:
    status: ApprovalStatus
    reason: str
    notification: NotificationResult | None = None


class ApprovalService:
    def __init__(
        self,
        *,
        store: JsonApprovalStore,
        notifier: TradeNotifier,
        authorized_phone_number: str | None = None,
        ttl_minutes: int = 10,
        now: Callable[[], datetime] | None = None,
        code_factory: Callable[[], str] | None = None,
    ) -> None:
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")

        self._store = store
        self._notifier = notifier
        self._authorized_phone_number = (
            authorized_phone_number.strip()
            if authorized_phone_number
            else None
        )
        self._ttl = timedelta(minutes=ttl_minutes)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._code_factory = code_factory or (
            lambda: secrets.token_urlsafe(24)
        )

    def _parse(self, value: str) -> datetime:
        return datetime.fromisoformat(value)

    def _record_status(
        self,
        record: ApprovalRecord,
    ) -> ApprovalStatus:
        status = ApprovalStatus(record.status)
        if status == ApprovalStatus.PENDING:
            if self._now() >= self._parse(record.expires_at):
                expired = replace(
                    record,
                    status=ApprovalStatus.EXPIRED.value,
                    resolved_at=self._now().isoformat(),
                )
                self._store.put(expired)
                return ApprovalStatus.EXPIRED
        return status

    def check_or_request(
        self,
        *,
        order: OrderRequest,
        estimated_fill_price: float,
        estimated_fees: float,
    ) -> ApprovalDecision:
        record = self._store.get(order.order_id)
        if record is not None:
            status = self._record_status(record)
            if status == ApprovalStatus.APPROVED:
                return ApprovalDecision(status, "human_approved")
            if status == ApprovalStatus.REJECTED:
                return ApprovalDecision(status, "human_rejected")
            if status == ApprovalStatus.EXPIRED:
                return ApprovalDecision(status, "approval_expired")
            return ApprovalDecision(status, "awaiting_human_approval")

        now = self._now()
        code = self._code_factory()
        for _ in range(10):
            if not self._store.find_by_code(code):
                break
            code = self._code_factory()
        else:
            return ApprovalDecision(
                ApprovalStatus.REJECTED,
                "approval_code_generation_failed",
            )

        record = ApprovalRecord(
            order_id=order.order_id,
            approval_code=code,
            status=ApprovalStatus.PENDING.value,
            created_at=now.isoformat(),
            expires_at=(now + self._ttl).isoformat(),
        )

        notional = order.quantity * estimated_fill_price
        message = (
            "TRADE APPROVAL REQUIRED\n"
            f"{order.side.value} {order.quantity:g} {order.symbol}\n"
            f"{order.order_type.value} est price ${estimated_fill_price:,.2f}\n"
            f"Notional ${notional:,.2f} | fees ${estimated_fees:,.2f}\n"
            f"Expires in {int(self._ttl.total_seconds() // 60)} min."
        )
        notification = self._notifier.send_approval_request(
            message,
            approval_code=code,
        )
        if not notification.sent:
            return ApprovalDecision(
                ApprovalStatus.REJECTED,
                "approval_notification_failed",
                notification,
            )

        self._store.put(record)
        return ApprovalDecision(
            ApprovalStatus.PENDING,
            "approval_requested",
            notification,
        )

    def handle_command(self, body: str) -> ApprovalDecision:
        parts = body.strip().split(maxsplit=1)
        if len(parts) != 2 or parts[0].upper() not in {"APPROVE", "REJECT"}:
            return ApprovalDecision(
                ApprovalStatus.REJECTED,
                "invalid_approval_command",
            )

        action = parts[0].upper()
        code = parts[1]
        matches = self._store.find_by_code(code)
        if len(matches) != 1:
            return ApprovalDecision(
                ApprovalStatus.REJECTED,
                "approval_code_not_found",
            )

        record = matches[0]
        status = self._record_status(record)
        if status != ApprovalStatus.PENDING:
            return ApprovalDecision(
                status,
                f"approval_{status.value.lower()}",
            )

        resolved_status = (
            ApprovalStatus.APPROVED
            if action == "APPROVE"
            else ApprovalStatus.REJECTED
        )
        resolved = replace(
            record,
            status=resolved_status.value,
            resolved_at=self._now().isoformat(),
        )
        self._store.put(resolved)
        return ApprovalDecision(
            resolved_status,
            (
                "human_approved"
                if resolved_status == ApprovalStatus.APPROVED
                else "human_rejected"
            ),
        )

    def handle_reply(
        self,
        *,
        from_number: str,
        body: str,
    ) -> ApprovalDecision:
        if self._authorized_phone_number is None:
            return ApprovalDecision(
                ApprovalStatus.REJECTED,
                "phone_sender_validation_not_configured",
            )
        if from_number.strip() != self._authorized_phone_number:
            return ApprovalDecision(
                ApprovalStatus.REJECTED,
                "unauthorized_sender",
            )
        return self.handle_command(body)
