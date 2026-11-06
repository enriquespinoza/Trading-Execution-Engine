"""Run offline tests and emit a fail-closed, hash-addressed CI report.

Software tests never authorize research acceptance or brokerage orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "research-ci-audit-v1"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_junit(path: Path) -> dict[str, int]:
    """Reject incomplete, empty, or inconsistent JUnit evidence."""
    root = ET.parse(path).getroot()
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = root.findall("testsuite")
    else:
        raise ValueError("Invalid JUnit root")
    if not suites:
        raise ValueError("No JUnit test suites")
    counts = {name: 0 for name in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for name in counts:
            value = int(suite.attrib[name])
            if value < 0:
                raise ValueError("Negative test count")
            counts[name] += value
    if not counts["tests"] or sum(counts[name] for name in ("failures", "errors", "skipped")) > counts["tests"]:
        raise ValueError("Empty or inconsistent JUnit counts")
    return counts


def git_sha(root: Path) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    except OSError:
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("audit-output"))
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    root = Path(__file__).resolve().parent.parent
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    junit = output / "junit.xml"
    logfile = output / "pytest.log"
    for path in (junit, logfile):
        path.unlink(missing_ok=True)

    started = time.monotonic()
    problems: list[str] = []
    exit_code = 1
    with logfile.open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "tests", f"--junitxml={junit}"],
                cwd=root, stdout=log, stderr=subprocess.STDOUT,
                timeout=args.timeout_seconds, check=False,
            )
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            problems.append("pytest_timeout")
        except OSError as exc:
            problems.append(f"pytest_launch_error:{type(exc).__name__}")

    try:
        counts = parse_junit(junit)
    except (ET.ParseError, ValueError, KeyError, OSError) as exc:
        counts = {name: 0 for name in ("tests", "failures", "errors", "skipped")}
        problems.append(f"junit_invalid:{type(exc).__name__}")
    if counts["tests"] and counts["tests"] == counts["skipped"]:
        problems.append("all_tests_skipped")

    status = "PASS" if exit_code == 0 and not problems and not (counts["failures"] or counts["errors"]) else "FAIL"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "classification": "SOFTWARE_TEST_ONLY",
        "research_acceptance": "NOT_ESTABLISHED",
        "independent_review": "NOT_PERFORMED",
        "broker_submission_permitted": False,
        "repository": os.getenv("GITHUB_REPOSITORY") or root.name,
        "git_commit": git_sha(root),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID") or None,
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "test_exit_code": exit_code,
        "test_counts": counts,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "problems": problems,
        "evidence_sha256": {
            "junit_xml": sha256_file(junit),
            "pytest_log": sha256_file(logfile),
            "runner": sha256_file(Path(__file__)),
            "requirements": sha256_file(root / "requirements.txt"),
            "pyproject": sha256_file(root / "pyproject.toml"),
        },
    }
    path = output / "audit_summary.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "audit_summary.sha256").write_text(f"{sha256_file(path)}  audit_summary.json\n", encoding="ascii")
    print(f"AUDIT {status}: {counts['tests']} tests, {counts['failures']} failures, "
          f"{counts['errors']} errors, {counts['skipped']} skipped; summary={path}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
