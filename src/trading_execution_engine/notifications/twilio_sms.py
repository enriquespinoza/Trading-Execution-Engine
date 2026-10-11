from __future__ import annotations

import os
from typing import Any

from trading_execution_engine.notifications.base import (
    NotificationResult,
    PreTradeAlert,
)


class TwilioSmsNotifier:
    """Send pre-trade alerts through Twilio without storing secrets in code."""

    def __init__(
        self,
        *,
        from_number: str,
        to_number: str,
        client: Any,
    ) -> None:
        if not from_number.strip():
            raise ValueError("from_number is required")
        if not to_number.strip():
            raise ValueError("to_number is required")
        self._from_number = from_number.strip()
        self._to_number = to_number.strip()
        self._client = client

    @classmethod
    def from_env(cls) -> "TwilioSmsNotifier":
        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError(
                'Twilio support is not installed. Run: '
                'python -m pip install -e ".[sms]"'
            ) from exc

        account_sid = os.environ["TWILIO_ACCOUNT_SID"]
        from_number = os.environ["TWILIO_FROM_NUMBER"]
        to_number = os.environ["TRADE_ALERT_TO_NUMBER"]

        api_key = os.environ.get("TWILIO_API_KEY")
        api_secret = os.environ.get("TWILIO_API_SECRET")
        auth_token = os.environ.get("TWILIO_AUTH_TOKEN")

        if api_key and api_secret:
            client = Client(api_key, api_secret, account_sid)
        elif auth_token:
            client = Client(account_sid, auth_token)
        else:
            raise RuntimeError(
                "Set TWILIO_API_KEY and TWILIO_API_SECRET, "
                "or set TWILIO_AUTH_TOKEN."
            )

        return cls(
            from_number=from_number,
            to_number=to_number,
            client=client,
        )

    def send(self, alert: PreTradeAlert) -> NotificationResult:
        try:
            message = self._client.messages.create(
                body=alert.to_message(),
                from_=self._from_number,
                to=self._to_number,
            )
        except Exception:
            # Fail closed without leaking provider details or credentials.
            return NotificationResult(
                sent=False,
                reason="twilio_send_failed",
            )

        return NotificationResult(
            sent=True,
            reason="sent",
            provider_message_id=getattr(message, "sid", None),
        )
