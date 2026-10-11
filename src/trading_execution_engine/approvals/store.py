from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApprovalRecord:
    order_id: str
    approval_code: str
    status: str
    created_at: str
    expires_at: str
    resolved_at: str | None = None
    order_fingerprint: str = ""
    consumed_at: str | None = None


class JsonApprovalStore:
    """Small durable store suitable for one local execution process."""

    def __init__(self, path: str | Path = "state/approvals.json") -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, ApprovalRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return {
            order_id: ApprovalRecord(**record)
            for order_id, record in payload.items()
        }

    def _write(self, records: dict[str, ApprovalRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                {
                    order_id: asdict(record)
                    for order_id, record in records.items()
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def get(self, order_id: str) -> ApprovalRecord | None:
        return self._read().get(order_id)

    def find_by_code(self, approval_code: str) -> list[ApprovalRecord]:
        return [
            record
            for record in self._read().values()
            if record.approval_code == approval_code
        ]

    def put(self, record: ApprovalRecord) -> None:
        records = self._read()
        records[record.order_id] = record
        self._write(records)
