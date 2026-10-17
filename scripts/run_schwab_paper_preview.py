from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_execution_engine.integrations.optimizer_targets import (
    load_optimizer_target_handoff,
    optimizer_targets_to_orders,
)
from trading_execution_engine.integrations.schwab.account_snapshot import (
    build_schwab_account_snapshot,
)
from trading_execution_engine.integrations.schwab.order_preview import (
    build_schwab_order_previews,
)


def _load_json(path: str | Path) -> dict:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"JSON input not found: {file_path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON input must contain an object: {file_path}")
    return payload


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate optimizer orders against a read-only Schwab/sandbox "
            "account snapshot and build local broker-compatible previews. "
            "No order submission is possible from this script."
        )
    )
    parser.add_argument("--targets", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--account-json", required=True)
    parser.add_argument("--quotes-json", required=True)
    parser.add_argument("--account-hash", required=True)
    parser.add_argument(
        "--fetched-at",
        default=None,
        help=(
            "Timezone-aware ISO-8601 timestamp for the capture. "
            "Defaults to current UTC time."
        ),
    )
    parser.add_argument(
        "--max-quote-age-minutes",
        type=float,
        default=5.0,
    )
    parser.add_argument(
        "--max-reference-price-drift-pct",
        type=float,
        default=10.0,
    )
    parser.add_argument("--output-report")
    args = parser.parse_args()

    handoff = load_optimizer_target_handoff(
        target_csv=args.targets,
        manifest_json=args.manifest,
        expected_artifact_sha256=args.expected_sha256,
    )
    orders = optimizer_targets_to_orders(handoff)

    account_payload = _load_json(args.account_json)
    quote_payload = _load_json(args.quotes_json)
    fetched_at = args.fetched_at or _utc_now_iso()

    snapshot = build_schwab_account_snapshot(
        account_hash=args.account_hash,
        account_payload=account_payload,
        quote_payload=quote_payload,
        required_symbols=[row.symbol for row in handoff.rows],
        fetched_at_utc=fetched_at,
        max_quote_age=timedelta(
            minutes=args.max_quote_age_minutes
        ),
    )

    previews = build_schwab_order_previews(
        handoff=handoff,
        snapshot=snapshot,
        orders=orders,
        max_reference_price_drift_pct=(
            args.max_reference_price_drift_pct
        ),
    )

    print("SCHWAB READ-ONLY ORDER PREFLIGHT")
    print("=" * 80)
    print(f"Contract:         {handoff.contract_version}")
    print(f"Builder:          {handoff.target_builder_version}")
    print(f"Session:          {handoff.as_of_session}")
    print(f"Execution state:  {handoff.execution_state}")
    print(f"Artifact SHA:     {handoff.artifact_sha256}")
    print(f"Snapshot SHA:     {snapshot.snapshot_sha256}")
    print(f"Cash balance:     ${snapshot.cash_balance:,.2f}")
    print(f"Order count:      {len(orders)}")
    print("Broker submission permitted: false")
    print()
    print("LOCAL BROKER-COMPATIBLE PREVIEWS")
    print("-" * 80)

    for preview in previews:
        print(
            f"{preview.order.side.value:4} "
            f"{preview.order.quantity:g} "
            f"{preview.order.symbol:8} "
            f"optimizer=${preview.optimizer_reference_price:,.2f} "
            f"schwab=${preview.schwab_reference_price:,.2f} "
            f"drift={preview.price_drift_pct:6.2f}% "
            f"notional=${preview.estimated_notional:,.2f} "
            f"{'APPROVED' if preview.approved else 'REJECTED'} "
            f"{preview.reason}"
        )

    approved_count = sum(preview.approved for preview in previews)
    rejected_count = len(previews) - approved_count

    print()
    print(f"Approved previews: {approved_count}")
    print(f"Rejected previews: {rejected_count}")
    print("External broker submission: false")

    report = {
        "validation_contract": "schwab-read-only-preflight-v1",
        "generated_at_utc": _utc_now_iso(),
        "optimizer": {
            "artifact_sha256": handoff.artifact_sha256,
            "handoff_contract_version": handoff.contract_version,
            "target_builder_version": handoff.target_builder_version,
            "as_of_session": handoff.as_of_session,
            "execution_state": handoff.execution_state,
        },
        "schwab_snapshot": {
            "snapshot_sha256": snapshot.snapshot_sha256,
            "fetched_at_utc": (
                snapshot.fetched_at_utc.astimezone(
                    timezone.utc
                ).isoformat()
            ),
            "cash_balance": snapshot.cash_balance,
            "available_funds": snapshot.available_funds,
            "buying_power": snapshot.buying_power,
            "broker_submission_permitted": False,
        },
        "preview": {
            "order_count": len(previews),
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "max_reference_price_drift_pct": (
                args.max_reference_price_drift_pct
            ),
            "external_broker_submission": False,
            "orders": [
                {
                    "order_id": preview.order.order_id,
                    "symbol": preview.order.symbol,
                    "side": preview.order.side.value,
                    "quantity": preview.order.quantity,
                    "optimizer_reference_price": (
                        preview.optimizer_reference_price
                    ),
                    "schwab_reference_price": (
                        preview.schwab_reference_price
                    ),
                    "price_drift_pct": preview.price_drift_pct,
                    "estimated_notional": (
                        preview.estimated_notional
                    ),
                    "approved": preview.approved,
                    "reason": preview.reason,
                    "schwab_order_spec": (
                        preview.schwab_order_spec
                    ),
                    "broker_submission_permitted": False,
                }
                for preview in previews
            ],
        },
    }

    if args.output_report:
        output_path = Path(args.output_report)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Report: {output_path}")

    if rejected_count:
        raise SystemExit(
            "PREFLIGHT BLOCKED: one or more orders failed local validation."
        )

    print()
    print(
        "PASS: optimizer orders reconcile to the read-only Schwab snapshot "
        "and have local broker-compatible previews."
    )
    print("No Schwab order endpoint was called.")


if __name__ == "__main__":
    main()
