from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from trading_execution_engine.approvals.service import ApprovalDecision, ApprovalService


class NtfyApprovalResponder:
    """Poll an ntfy response topic and apply APPROVE/REJECT commands."""

    def __init__(
        self,
        *,
        service: ApprovalService,
        base_url: str,
        response_topic: str,
        access_token: str | None = None,
    ) -> None:
        self._service = service
        self._base_url = base_url.rstrip("/")
        self._response_topic = response_topic.strip()
        self._access_token = access_token.strip() if access_token else None

    @classmethod
    def from_env(
        cls,
        *,
        service: ApprovalService,
    ) -> "NtfyApprovalResponder":
        return cls(
            service=service,
            base_url=os.environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
            response_topic=os.environ["NTFY_RESPONSE_TOPIC"],
            access_token=os.environ.get("NTFY_ACCESS_TOKEN"),
        )

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

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
        url = (
            f"{self._base_url}/{self._response_topic}/json?{query}"
        )
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
            payload = json.loads(line)
            message = payload.get("message")
            if not isinstance(message, str):
                continue
            normalized = message.strip()
            if not (
                normalized.upper().startswith("APPROVE ")
                or normalized.upper().startswith("REJECT ")
            ):
                continue
            decisions.append(
                self._service.handle_command(normalized)
            )

        return decisions
