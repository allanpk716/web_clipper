"""S01 integration tests: stderr purity under --quiet and agent doctor end-to-end.

Verifies R033 (no Python traceback on stderr) and R034 (doctor runs without crash)
using subprocess-level tests that capture real stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

# Use the CLI entry point as invoked by `python -m web_clip_helper.cli`
CLI_MODULE = "web_clip_helper.cli"

# Traceback indicators that should NEVER appear on stderr in --quiet mode
TRACEBACK_MARKERS = ("Traceback (most recent call last)",)


def _run_cli(*args: str, expect_failure: bool = False) -> subprocess.CompletedProcess:
    """Run the CLI as a subprocess, capturing stdout and stderr separately."""
    result = subprocess.run(
        [sys.executable, "-m", CLI_MODULE, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if not expect_failure:
        assert result.returncode == 0, (
            f"CLI exited {result.returncode}\nstdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
        )
    return result


# ── stderr purity tests (R033) ────────────────────────────────────


class TestStderrPurity:
    """Verify --quiet mode produces no Python traceback on stderr."""

    def test_stderr_no_traceback_quiet_list(self) -> None:
        """--quiet list should produce zero Python tracebacks on stderr."""
        result = _run_cli("--quiet", "list")

        for marker in TRACEBACK_MARKERS:
            assert marker not in result.stderr, (
                f"Found traceback marker '{marker}' on stderr:\n{result.stderr}"
            )

    def test_stderr_no_traceback_quiet_clip_bad_url(self) -> None:
        """--quiet clip with invalid URL should not produce Python tracebacks on stderr.

        The command will fail (non-zero exit), but stderr must be clean of tracebacks.
        """
        result = _run_cli("--quiet", "clip", "not-a-url", expect_failure=True)
        assert result.returncode != 0, "Expected non-zero exit for bad URL"

        for marker in TRACEBACK_MARKERS:
            assert marker not in result.stderr, (
                f"Found traceback marker '{marker}' on stderr:\n{result.stderr}"
            )


# ── agent doctor integration tests (R034) ─────────────────────────


class TestDoctorIntegration:
    """Verify agent doctor runs end-to-end and all checks have valid status."""

    def _run_doctor(self) -> tuple[list[dict], str]:
        """Run agent doctor, return (checks_list, raw_stdout)."""
        result = _run_cli("agent", "doctor")
        assert result.returncode == 0, (
            f"doctor exited {result.returncode}\nstderr: {result.stderr[:500]}"
        )

        # Doctor emits JSONL lines; find the result line with checks
        checks: list[dict] = []
        for line in result.stdout.strip().splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "result" and isinstance(obj.get("data", {}).get("checks"), list):
                checks = obj["data"]["checks"]

        assert checks, f"No checks found in doctor output:\n{result.stdout[:1000]}"
        return checks, result.stdout

    def test_doctor_all_checks_have_valid_status(self) -> None:
        """Every check returned by doctor must have status in (pass, fail, warning)."""
        valid_statuses = {"pass", "fail", "warning"}
        checks, _ = self._run_doctor()

        for check in checks:
            status = check.get("status", "")
            assert status in valid_statuses, (
                f"Check '{check.get('name')}' has invalid status '{status}'. "
                f"Expected one of {valid_statuses}."
            )

    def test_doctor_all_checks_have_required_fields(self) -> None:
        """Every check must have name, status, and message fields."""
        checks, _ = self._run_doctor()

        for check in checks:
            assert "name" in check, f"Check missing 'name' field: {check}"
            assert "status" in check, f"Check missing 'status' field: {check}"
            assert "message" in check, f"Check missing 'message' field: {check}"

    def test_doctor_no_skip_status(self) -> None:
        """skip status should be mapped to pass per D035.

        The SDK doctor command and our health checks should never emit
        status='skip' — skip cases are mapped to 'pass' with a skip message.
        """
        checks, _ = self._run_doctor()

        for check in checks:
            status = check.get("status", "")
            assert status != "skip", (
                f"Check '{check.get('name')}' has status='skip', which should be "
                f"mapped to 'pass' with a skip message per D035."
            )

    def test_doctor_overall_status_valid(self) -> None:
        """Overall doctor status must be pass, fail, or warning."""
        result = _run_cli("agent", "doctor")

        for line in result.stdout.strip().splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "result" and "status" in obj.get("data", {}):
                overall = obj["data"]["status"]
                assert overall in ("pass", "fail", "warning"), (
                    f"Overall doctor status '{overall}' is not valid."
                )
                return

        pytest.fail("No doctor result line found with overall status")
