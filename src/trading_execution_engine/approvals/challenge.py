from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any

from trading_execution_engine.models.order import OrderRequest


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def trade_fingerprint(
    *,
    order: OrderRequest,
    estimated_fill_price: float,
    estimated_fees: float,
) -> str:
    payload = {
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "quantity": format(order.quantity, ".12g"),
        "order_type": order.order_type.value,
        "limit_price": (
            None
            if order.limit_price is None
            else format(order.limit_price, ".12g")
        ),
        "estimated_fill_price": format(estimated_fill_price, ".12g"),
        "estimated_fees": format(estimated_fees, ".12g"),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class VerifiedApprovalCommand:
    action: str
    order_id: str
    nonce: str
    fingerprint: str
    expires_at: str


class ApprovalSigner:
    """Create and verify tamper-evident, action-specific approval tokens."""

    def __init__(self, signing_key: str | bytes) -> None:
        key = (
            signing_key.encode("utf-8")
            if isinstance(signing_key, str)
            else signing_key
        )
        if len(key) < 32:
            raise ValueError(
                "approval signing key must be at least 32 bytes"
            )
        self._key = key

    @classmethod
    def from_env(cls) -> "ApprovalSigner":
        value = os.environ.get("TRADE_APPROVAL_SIGNING_KEY", "")
        if not value:
            raise RuntimeError(
                "TRADE_APPROVAL_SIGNING_KEY is required for signed approvals"
            )
        return cls(value)

    def build_command(
        self,
        *,
        action: str,
        order_id: str,
        nonce: str,
        fingerprint: str,
        expires_at: str,
    ) -> str:
        normalized_action = action.upper()
        if normalized_action not in {"APPROVE", "REJECT"}:
            raise ValueError("unsupported approval action")

        payload = {
            "v": 1,
            "action": normalized_action,
            "order_id": order_id,
            "nonce": nonce,
            "fingerprint": fingerprint,
            "expires_at": expires_at,
        }
        encoded = _b64encode(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signature = _b64encode(
            hmac.new(
                self._key,
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        return f"{normalized_action} {encoded}.{signature}"

    def verify_command(
        self,
        command: str,
    ) -> VerifiedApprovalCommand | None:
        parts = command.strip().split(maxsplit=1)
        if len(parts) != 2:
            return None

        action, token = parts
        action = action.upper()
        if action not in {"APPROVE", "REJECT"}:
            return None

        try:
            encoded, supplied_signature = token.split(".", 1)
            expected_signature = _b64encode(
                hmac.new(
                    self._key,
                    encoded.encode("ascii"),
                    hashlib.sha256,
                ).digest()
            )
            if not hmac.compare_digest(
                supplied_signature,
                expected_signature,
            ):
                return None

            payload: dict[str, Any] = json.loads(
                _b64decode(encoded).decode("utf-8")
            )
        except (
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            return None

        if payload.get("v") != 1:
            return None
        if payload.get("action") != action:
            return None

        required = (
            "order_id",
            "nonce",
            "fingerprint",
            "expires_at",
        )
        if any(
            not isinstance(payload.get(field), str)
            or not payload[field]
            for field in required
        ):
            return None

        return VerifiedApprovalCommand(
            action=action,
            order_id=payload["order_id"],
            nonce=payload["nonce"],
            fingerprint=payload["fingerprint"],
            expires_at=payload["expires_at"],
        )
