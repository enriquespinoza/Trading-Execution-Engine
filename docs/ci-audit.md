# Automated software audit pilot

The GitHub Actions job runs **offline Execution Engine tests** on pull requests, pushes to main, and weekdays. Its GitHub permission is read-only. The test workflow contains no broker credentials, no live market data calls, and no broker order submission.

Run locally after installing development dependencies:

    python -m pip install -e ".[dev]"
    python scripts/run_ci_audit.py

Outputs under audit-output/: junit.xml, pytest.log, audit_summary.json, and audit_summary.sha256.

The audit fails when pytest fails, the report is absent, empty, malformed or entirely skipped, or when the test process times out. The manifest contains the checked-out commit, Python runtime, dependency-file hashes, test counts, and output-file hashes.

**Fixed research boundary:** research_acceptance=NOT_ESTABLISHED, independent_review=NOT_PERFORMED, broker_submission_permitted=false. Passing software tests never authorizes trading or establishes predictive performance.

The summary SHA-256 detects modifications to the JSON file, but is not a signed attestation or proof of original data provenance. GitHub artifact retention is 90 days in this workflow; independent durable write-protected storage must be built before relying on these artifacts for long-term research confirmation. Missing scheduled runs require a separate detector. Logs must be reviewed for secrets and proprietary data before expanding this test suite to credentialed or market-data tests.

The project's dependencies are not currently fully hash-locked. This pilot is a software-health gate, not a reproducible scientific environment certification.
