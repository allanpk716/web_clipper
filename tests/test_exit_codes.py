"""Tests verifying exit code conventions: 0 for success, non-zero for failure.

Covers three core scenarios:
  1. No subcommand → SDK Envelope result output + exit 0
  2. clip without args → error envelope + exit 2 (INPUT_INVALID)
  3. get nonexistent ID → error envelope + exit 3 (NOT_FOUND)

Each scenario is tested via subprocess (``python -m``) which exercises
the full SDK App.run() code path including _SDKGroup exception interception.
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


def _parse_envelopes(stdout: str) -> list[dict]:
    """Parse stdout into a list of SDK Envelope JSON objects."""
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


# ── Scenario 1: No subcommand → Envelope result + exit 0 ────────


class TestNoSubcommandHelp:
    """No subcommand should emit SDK Envelope result and exit 0."""

    def test_no_subcommand_subprocess_exit_0(self) -> None:
        """python -m web_clip_helper.cli (no args) should exit 0."""
        r = _run_cli()
        assert r.returncode == 0

    def test_no_subcommand_subprocess_envelope_result(self) -> None:
        """python -m web_clip_helper.cli should output SDK Envelope with type=result."""
        r = _run_cli()
        envelopes = _parse_envelopes(r.stdout)
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1
        assert "commands" in results[0]["data"]


# ── Scenario 2: clip without args → error + exit 2 ──────────────


class TestClipNoArgs:
    """clip command without URL or text should exit 2 (INPUT_INVALID)."""

    def test_clip_no_args_subprocess_exit_2(self) -> None:
        """python -m web_clip_helper.cli clip (no args) should exit 2."""
        r = _run_cli("clip")
        assert r.returncode == 2

    def test_clip_no_args_subprocess_error_envelope(self) -> None:
        """clip without args should output SDK Envelope with type=error."""
        r = _run_cli("clip")
        envelopes = _parse_envelopes(r.stdout)
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0]["error_code"] == "INPUT_INVALID"
        msg = errors[0].get("message", "")
        assert "[clip]" in msg


# ── Scenario 3: get nonexistent ID → error + exit 3 ─────────────


class TestGetNonexistent:
    """get command with nonexistent ID should exit 3 (NOT_FOUND)."""

    def test_get_nonexistent_subprocess_exit_3(self) -> None:
        """python -m web_clip_helper.cli get 999999 should exit 3."""
        r = _run_cli("get", "999999")
        assert r.returncode == 3

    def test_get_nonexistent_subprocess_error_envelope(self) -> None:
        """get nonexistent ID should output SDK Envelope with type=error."""
        r = _run_cli("get", "999999")
        envelopes = _parse_envelopes(r.stdout)
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0]["error_code"] == "NOT_FOUND"
        msg = errors[0].get("message", "")
        assert "[get]" in msg


# ── Additional success-path exit code tests ──────────────────────


class TestExitCodesSuccess:
    """Commands should exit 0 on success."""

    def test_list_success_exit_0(self) -> None:
        """list command should exit 0 even on empty database."""
        r = _run_cli("list")
        assert r.returncode == 0

    def test_tags_success_exit_0(self) -> None:
        """tags command should exit 0 even on empty database."""
        r = _run_cli("tags")
        assert r.returncode == 0

    def test_config_list_exit_0(self) -> None:
        """config list should exit 0."""
        r = _run_cli("config", "list")
        assert r.returncode == 0

    def test_search_success_exit_0(self) -> None:
        """search should exit 0 even with no results."""
        r = _run_cli("search", "nonexistent-query-xyz")
        assert r.returncode == 0


class TestExitCodesFailure:
    """Commands should exit non-zero on failure."""

    def test_config_get_invalid_key_exit_2(self) -> None:
        """config get with invalid key should exit 2 (CONFIG_ERROR)."""
        r = _run_cli("config", "get", "nonexistent.key")
        assert r.returncode == 2
