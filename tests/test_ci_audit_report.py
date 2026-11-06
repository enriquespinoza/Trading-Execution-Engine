"""Contract tests for the fail-closed software audit runner."""
from pathlib import Path

import pytest

from scripts.run_ci_audit import parse_junit, sha256_file


def test_accepts_valid_junit(tmp_path: Path) -> None:
    file = tmp_path / "junit.xml"
    file.write_text('<testsuites><testsuite tests="4" failures="1" errors="0" skipped="1" /></testsuites>')
    assert parse_junit(file) == {"tests": 4, "failures": 1, "errors": 0, "skipped": 1}


@pytest.mark.parametrize("payload", [
    "<bad />",
    "<testsuites />",
    '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0" /></testsuites>',
    '<testsuites><testsuite tests="1" failures="2" errors="0" skipped="0" /></testsuites>',
    '<testsuites><testsuite tests="1" failures="0" errors="0" /></testsuites>',
])
def test_rejects_invalid_reports(tmp_path: Path, payload: str) -> None:
    file = tmp_path / "junit.xml"
    file.write_text(payload)
    with pytest.raises((ValueError, KeyError)):
        parse_junit(file)


def test_missing_evidence_is_not_hashed(tmp_path: Path) -> None:
    assert sha256_file(tmp_path / "missing") is None
