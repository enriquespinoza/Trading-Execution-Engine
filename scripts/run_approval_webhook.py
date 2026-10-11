import os

from trading_execution_engine.approvals.twilio_webhook import create_app


app = create_app()

if __name__ == "__main__":
    app.run(
        host=os.environ.get("APPROVAL_WEBHOOK_HOST", "127.0.0.1"),
        port=int(os.environ.get("APPROVAL_WEBHOOK_PORT", "5000")),
        debug=False,
    )
