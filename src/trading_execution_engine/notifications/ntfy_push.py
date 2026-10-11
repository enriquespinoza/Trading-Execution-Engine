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
    """Push trade alerts through authenticated ntfy topics."""

    def __init__(
        self,
        *,
        base_url: str,
        alert_topic: str,
        response_topic: str,
        alert_publish_token: str,
        response_publish_token: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._alert_topic = alert_topic.strip()
        self._response_topic = response_topic.strip()
        self._alert_publish_token = alert_publish_token.strip()
        self._response_publish_token = response_publish_token.strip()

        if not self._alert_topic:
            raise ValueError("alert_topic is required")
        if not self._response_topic:
            raise ValueError("response_topic is required")
        if not self._alert_publish_token:
            raise ValueError("alert_publish_token is required")
        if not self._response_publish_token:
            raise ValueError("response_publish_token is required")

    @classmethod
    def from_env(cls) -> "NtfyPushNotifier":
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise RuntimeError(
                'Push support requires python-dotenv. Run: '
                'python -m pip install -e ".[push]"'
            ) from exc

        load_dotenv()
        return cls(
            base_url=os.environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
            alert_topic=os.environ["NTFY_ALERT_TOPIC"],
            response_topic=os.environ["NTFY_RESPONSE_TOPIC"],
            alert_publish_token=os.environ["NTFY_ALERT_PUBLISH_TOKEN"],
            response_publish_token=os.environ["NTFY_RESPONSE_PUBLISH_TOKEN"],
        )

    def _publish_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._alert_publish_token}",
        }

    def _publish(self, payload: dict) -> NotificationResult:
        request = urllib.request.Request(
            url=f"{self._base_url}/",
            method="POST",
            headers=self._publish_headers(),
            data=json.dumps(payload).encode("utf-8"),
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ):
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
        approve_command: str,
        reject_command: str,
    ) -> NotificationResult:
        response_url = f"{self._base_url}/{self._response_topic}"
        action_headers = {
            "Authorization": f"Bearer {self._response_publish_token}",
            "Content-Type": "text/plain",
        }

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
                        "url": response_url,
                        "method": "POST",
                        "headers": action_headers,
                        "body": approve_command,
                        "clear": True,
                    },
                    {
                        "action": "http",
                        "label": "Reject",
                        "url": response_url,
                        "method": "POST",
                        "headers": action_headers,
                        "body": reject_command,
                        "clear": True,
                    },
                ],
            }
        )
