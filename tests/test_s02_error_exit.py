"""Subprocess-level end-to-end tests for single error emit + exit code consistency.

Validates that after T01/T02 refactoring:
  1. Every failure scenario emits exactly ONE type=error JSONL line (no dual emit).
  2. The process exit code matches the semantic mapping in error_codes.py.
  3. Adapter errors propagate their error_code correctly without double-emit.

Uses ``subprocess.run`` to exercise the full code path (SDK App.run() +
_SDKGroup exception interception), not CliRunner which may mask stderr behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI via subprocess and return the CompletedProcess result."""
    return subprocess.run(
        [sys.executable, "-m", "web_clip_helper.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts, ignoring blank lines."""
    lines = [ln for ln in output.strip().splitlines() if ln.strip()]
    result = []
    for line in lines:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # skip non-JSON lines (e.g. Rich text)
    return result


def _count_error_lines(envelopes: list[dict]) -> int:
    """Count envelopes with type=error."""
    return sum(1 for e in envelopes if e.get("type") == "error")


def _error_codes(envelopes: list[dict]) -> list[str]:
    """Extract all error_code values from error envelopes."""
    return [
        e.get("error_code", "")
        for e in envelopes
        if e.get("type") == "error"
    ]


# ── clip no args → exit 2 (INPUT_INVALID), single error line ────


class TestClipNoArgsExit2:
    """clip without URL or text should exit 2 (INPUT_INVALID) with exactly one error line."""

    def test_clip_no_args_exit_code(self) -> None:
        r = _run_cli("clip")
        assert r.returncode == 2, f"Expected exit 2, got {r.returncode}"

    def test_clip_no_args_single_error_line(self) -> None:
        r = _run_cli("clip")
        envelopes = _parse_jsonl(r.stdout)
        error_count = _count_error_lines(envelopes)
        assert error_count == 1, (
            f"Expected exactly 1 error line, got {error_count}. "
            f"Envelopes: {json.dumps(envelopes, ensure_ascii=False)}"
        )

    def test_clip_no_args_error_code(self) -> None:
        r = _run_cli("clip")
        envelopes = _parse_jsonl(r.stdout)
        codes = _error_codes(envelopes)
        assert "INPUT_INVALID" in codes, f"Expected INPUT_INVALID, got {codes}"


# ── clip invalid URL → exit 4 (FETCH_ERROR), single error line ──


class TestClipInvalidUrlExit4:
    """clip with an invalid URL should exit 4 (FETCH_ERROR) with exactly one error line."""

    def test_clip_invalid_url_exit_code(self) -> None:
        r = _run_cli("clip", "not-a-url")
        assert r.returncode == 4, f"Expected exit 4, got {r.returncode}. stdout: {r.stdout!r}"

    def test_clip_invalid_url_single_error_line(self) -> None:
        r = _run_cli("clip", "not-a-url")
        envelopes = _parse_jsonl(r.stdout)
        error_count = _count_error_lines(envelopes)
        assert error_count == 1, (
            f"Expected exactly 1 error line, got {error_count}. "
            f"Envelopes: {json.dumps(envelopes, ensure_ascii=False)}"
        )

    def test_clip_invalid_url_error_code(self) -> None:
        r = _run_cli("clip", "not-a-url")
        envelopes = _parse_jsonl(r.stdout)
        codes = _error_codes(envelopes)
        assert len(codes) == 1, f"Expected 1 error code, got {len(codes)}: {codes}"
        assert codes[0] in ("FETCH_ERROR", "ROUTING_ERROR", "INPUT_INVALID"), (
            f"Expected FETCH_ERROR/ROUTING_ERROR/INPUT_INVALID, got {codes[0]}"
        )


# ── get nonexistent ID → exit 3 (NOT_FOUND), single error line ──


class TestGetNonexistentExit3:
    """get with nonexistent ID should exit 3 (NOT_FOUND) with exactly one error line."""

    def test_get_nonexistent_exit_code(self) -> None:
        r = _run_cli("get", "999999")
        assert r.returncode == 3, f"Expected exit 3, got {r.returncode}"

    def test_get_nonexistent_single_error_line(self) -> None:
        r = _run_cli("get", "999999")
        envelopes = _parse_jsonl(r.stdout)
        error_count = _count_error_lines(envelopes)
        assert error_count == 1, (
            f"Expected exactly 1 error line, got {error_count}. "
            f"Envelopes: {json.dumps(envelopes, ensure_ascii=False)}"
        )

    def test_get_nonexistent_error_code(self) -> None:
        r = _run_cli("get", "999999")
        envelopes = _parse_jsonl(r.stdout)
        codes = _error_codes(envelopes)
        assert "NOT_FOUND" in codes, f"Expected NOT_FOUND, got {codes}"


# ── Cross-cutting: all failure scenarios produce exactly one error ─


class TestSingleErrorLineAllFailures:
    """Verify no failure scenario produces more than one type=error line.

    This is the core regression test for the dual-emit bug fixed in S02.
    """

    def test_clip_no_args_single_error(self) -> None:
        r = _run_cli("clip")
        envelopes = _parse_jsonl(r.stdout)
        assert _count_error_lines(envelopes) == 1

    def test_clip_invalid_url_single_error(self) -> None:
        r = _run_cli("clip", "not-a-url")
        envelopes = _parse_jsonl(r.stdout)
        assert _count_error_lines(envelopes) == 1

    def test_get_nonexistent_single_error(self) -> None:
        r = _run_cli("get", "999999")
        envelopes = _parse_jsonl(r.stdout)
        assert _count_error_lines(envelopes) == 1

    def test_delete_nonexistent_single_error(self) -> None:
        r = _run_cli("delete", "999999")
        envelopes = _parse_jsonl(r.stdout)
        assert _count_error_lines(envelopes) == 1, (
            f"delete nonexistent should have exactly 1 error, "
            f"got {_count_error_lines(envelopes)}"
        )

    def test_update_no_options_single_error(self) -> None:
        """update with no options should produce exactly one INPUT_INVALID error."""
        r = _run_cli("update", "1")
        envelopes = _parse_jsonl(r.stdout)
        assert _count_error_lines(envelopes) == 1, (
            f"update with no options should have exactly 1 error, "
            f"got {_count_error_lines(envelopes)}"
        )


# ── Exit code semantic consistency ───────────────────────────────


class TestExitCodeSemantics:
    """Verify exit codes match error_codes.py semantic mapping."""

    def test_input_invalid_maps_to_2(self) -> None:
        """INPUT_INVALID should always produce exit code 2."""
        # clip without args
        r = _run_cli("clip")
        assert r.returncode == 2

    def test_not_found_maps_to_3(self) -> None:
        """NOT_FOUND should always produce exit code 3."""
        r = _run_cli("get", "999999")
        assert r.returncode == 3

    def test_fetch_or_routing_error_maps_to_4(self) -> None:
        """FETCH_ERROR or ROUTING_ERROR should produce exit code 4."""
        r = _run_cli("clip", "not-a-url")
        assert r.returncode == 4, (
            f"Expected exit 4 for fetch/routing error, got {r.returncode}"
        )
