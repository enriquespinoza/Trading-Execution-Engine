from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from trading_execution_engine.notifications.base import (
    NotificationResult,
    PreTradeAlert,
    TradeNotifier,
)


class NtfyPushNotifier(TradeNotifier):
    """Push trade alerts through ntfy without exposing a local webhook."""

    def __init__(
        self,
        *,
        base_url: str,
        alert_topic: str,
        response_topic: str,
        access_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._alert_topic = alert_topic.strip()
        self._response_topic = response_topic.strip()
        self._access_token = access_token.strip() if access_token else None

        if not self._alert_topic:
            raise ValueError("alert_topic is required")
        if not self._response_topic:
            raise ValueError("response_topic is required")

    @classmethod
    def from_env(cls) -> "NtfyPushNotifier":
        return cls(
            base_url=os.environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
            alert_topic=os.environ["NTFY_ALERT_TOPIC"],
            response_topic=os.environ["NTFY_RESPONSE_TOPIC"],
            access_token=os.environ.get("NTFY_ACCESS_TOKEN"),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def _publish(self, payload: dict) -> NotificationResult:
        request = urllib.request.Request(
            url=f"{self._base_url}/",
            method="POST",
            headers=self._headers(),
            data=json.dumps(payload).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return NotificationResult(False, "ntfy_publish_failed")

        return NotificationResult(
            True,
            "sent",
            provider_message_id=body.get("id"),
        )

    def send_message(self, message: str) -> NotificationResult:
        return self._publish(
            {
                "topic": self._alert_topic,
                "title": "Trading Execution Engine",
                "message": message,
                "priority": 4,
            }
        )

    def send(self, alert: PreTradeAlert) -> NotificationResult:
        return self.send_message(alert.to_message())

    def send_approval_request(
        self,
        message: str,
        *,
        approval_code: str,
    ) -> NotificationResult:
        response_base = (
            f"{self._base_url}/{self._response_topic}"
        )

        return self._publish(
            {
                "topic": self._alert_topic,
                "title": "Trade approval required",
                "message": message,
                "priority": 5,
                "tags": ["warning"],
                "actions": [
                    {
                        "action": "http",
                        "label": "Approve",
                        "url": response_base,
                        "method": "POST",
                        "body": f"APPROVE {approval_code}",
                        "clear": True,
                    },
                    {
                        "action": "http",
                        "label": "Reject",
                        "url": response_base,
                        "method": "POST",
                        "body": f"REJECT {approval_code}",
                        "clear": True,
                    },
                ],
            }
        )
