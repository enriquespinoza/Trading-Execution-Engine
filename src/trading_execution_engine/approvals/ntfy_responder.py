from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from trading_execution_engine.approvals.service import (
    ApprovalDecision,
    ApprovalService,
)


class NtfyApprovalResponder:
    """Poll an authenticated response topic and validate signed commands."""

    def __init__(
        self,
        *,
        service: ApprovalService,
        base_url: str,
        response_topic: str,
        response_read_token: str,
    ) -> None:
        self._service = service
        self._base_url = base_url.rstrip("/")
        self._response_topic = response_topic.strip()
        self._response_read_token = response_read_token.strip()

        if not self._response_topic:
            raise ValueError("response_topic is required")
        if not self._response_read_token:
            raise ValueError("response_read_token is required")

    @classmethod
    def from_env(
        cls,
        *,
        service: ApprovalService,
    ) -> "NtfyApprovalResponder":
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise RuntimeError(
                'Push support requires python-dotenv. Run: '
                'python -m pip install -e ".[push]"'
            ) from exc

        load_dotenv()
        return cls(
            service=service,
            base_url=os.environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
            response_topic=os.environ["NTFY_RESPONSE_TOPIC"],
            response_read_token=os.environ["NTFY_RESPONSE_READ_TOKEN"],
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._response_read_token}",
        }

    def poll_since(
        self,
        since: datetime,
    ) -> list[ApprovalDecision]:
        since_iso = since.astimezone(timezone.utc).isoformat()
        query = urllib.parse.urlencode(
            {
                "poll": "1",
                "since": since_iso,
            }
        )
        url = f"{self._base_url}/{self._response_topic}/json?{query}"
        request = urllib.request.Request(
            url=url,
            headers=self._headers(),
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                lines = response.read().decode("utf-8").splitlines()
        except (urllib.error.URLError, TimeoutError):
            return []

        decisions: list[ApprovalDecision] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            message = payload.get("message")
            if not isinstance(message, str):
                continue

            decisions.append(
                self._service.handle_command(message.strip())
            )

        return decisions
