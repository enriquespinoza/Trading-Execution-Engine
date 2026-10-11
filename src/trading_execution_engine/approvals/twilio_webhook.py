from __future__ import annotations

import os
from pathlib import Path

from trading_execution_engine.approvals.service import ApprovalService
from trading_execution_engine.approvals.store import JsonApprovalStore
from trading_execution_engine.notifications.twilio_sms import TwilioSmsNotifier


def create_app():
    try:
        from dotenv import load_dotenv
        from flask import Flask, Response, abort, request
        from twilio.request_validator import RequestValidator
        from twilio.twiml.messaging_response import MessagingResponse
    except ImportError as exc:
        raise RuntimeError(
            'Approval webhook dependencies are not installed. Run: '
            'python -m pip install -e ".[sms]"'
        ) from exc

    load_dotenv()

    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    authorized_number = os.environ["TRADE_ALERT_TO_NUMBER"]
    configured_url = os.environ.get("TWILIO_APPROVAL_WEBHOOK_URL")
    store_path = Path(
        os.environ.get(
            "TRADE_APPROVAL_STORE",
            "state/approvals.json",
        )
    )

    notifier = TwilioSmsNotifier.from_env()
    service = ApprovalService(
        store=JsonApprovalStore(store_path),
        notifier=notifier,
        authorized_phone_number=authorized_number,
        ttl_minutes=int(
            os.environ.get("TRADE_APPROVAL_TTL_MINUTES", "10")
        ),
    )
    validator = RequestValidator(auth_token)

    app = Flask(__name__)

    @app.post("/sms/approval")
    def sms_approval():
        signature = request.headers.get("X-Twilio-Signature", "")
        validation_url = configured_url or request.url

        if not validator.validate(
            validation_url,
            request.form,
            signature,
        ):
            abort(403)

        decision = service.handle_reply(
            from_number=request.form.get("From", ""),
            body=request.form.get("Body", ""),
        )

        response = MessagingResponse()
        # Return an empty TwiML response: the inbound command is recorded,
        # but the webhook does not create another outgoing SMS automatically.
        return Response(
            str(response),
            status=200,
            mimetype="application/xml",
            headers={
                "X-Trade-Approval-Status": decision.status.value,
                "X-Trade-Approval-Reason": decision.reason,
            },
        )

    return app
