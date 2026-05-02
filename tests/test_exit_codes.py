"""Tests verifying exit code conventions: 0 for success, 1 for failure.

Covers three core scenarios from the Typer callback refactor:
  1. No subcommand → JSONL help output + exit 0
  2. clip without args → error JSONL + exit 1
  3. get nonexistent ID → error JSONL + exit 1

Each scenario is tested via both subprocess (`python -m`) and direct
`app()` invocation to ensure Exit codes propagate correctly through
both code paths.
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


def _run_cli_direct(args: list[str]) -> subprocess.CompletedProcess:
    """Run CLI via direct app() call and return the CompletedProcess result."""
    return subprocess.run(
        [
            sys.executable, "-c",
            f"import sys; sys.argv = {['test'] + args}; "
            "from web_clip_helper.cli import app; app()",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── Scenario 1: No subcommand → JSONL help + exit 0 ─────────────


class TestNoSubcommandHelp:
    """No subcommand should emit JSONL help and exit 0."""

    def test_no_subcommand_subprocess_exit_0(self) -> None:
        """python -m web_clip_helper.cli (no args) should exit 0."""
        r = _run_cli()
        assert r.returncode == 0

    def test_no_subcommand_subprocess_jsonl_help(self) -> None:
        """python -m web_clip_helper.cli should output JSONL with type=help."""
        r = _run_cli()
        data = json.loads(r.stdout.strip())
        assert data["type"] == "help"
        assert "commands" in data

    def test_no_subcommand_direct_exit_0(self) -> None:
        """Direct app() with no args should exit 0."""
        r = _run_cli_direct([])
        assert r.returncode == 0

    def test_no_subcommand_direct_jsonl_help(self) -> None:
        """Direct app() with no args should output JSONL with type=help."""
        r = _run_cli_direct([])
        data = json.loads(r.stdout.strip())
        assert data["type"] == "help"
        assert "commands" in data


# ── Scenario 2: clip without args → error + exit 1 ──────────────


class TestClipNoArgs:
    """clip command without URL or text should exit 1."""

    def test_clip_no_args_subprocess_exit_1(self) -> None:
        """python -m web_clip_helper.cli clip (no args) should exit 1."""
        r = _run_cli("clip")
        assert r.returncode == 1

    def test_clip_no_args_subprocess_error_jsonl(self) -> None:
        """clip without args should output JSONL with type=error."""
        r = _run_cli("clip")
        data = json.loads(r.stdout.strip())
        assert data["type"] == "error"
        assert data["stage"] == "clip"

    def test_clip_no_args_direct_exit_1(self) -> None:
        """Direct app() clip (no args) should exit 1."""
        r = _run_cli_direct(["clip"])
        assert r.returncode == 1

    def test_clip_no_args_direct_error_jsonl(self) -> None:
        """Direct app() clip (no args) should output JSONL with type=error."""
        r = _run_cli_direct(["clip"])
        data = json.loads(r.stdout.strip())
        assert data["type"] == "error"
        assert data["stage"] == "clip"


# ── Scenario 3: get nonexistent ID → error + exit 1 ─────────────


class TestGetNonexistent:
    """get command with nonexistent ID should exit 1."""

    def test_get_nonexistent_subprocess_exit_1(self) -> None:
        """python -m web_clip_helper.cli get 999999 should exit 1."""
        r = _run_cli("get", "999999")
        assert r.returncode == 1

    def test_get_nonexistent_subprocess_error_jsonl(self) -> None:
        """get nonexistent ID should output JSONL with type=error."""
        r = _run_cli("get", "999999")
        data = json.loads(r.stdout.strip())
        assert data["type"] == "error"
        assert data["stage"] == "get"

    def test_get_nonexistent_direct_exit_1(self) -> None:
        """Direct app() get nonexistent ID should exit 1."""
        r = _run_cli_direct(["get", "999999"])
        assert r.returncode == 1

    def test_get_nonexistent_direct_error_jsonl(self) -> None:
        """Direct app() get nonexistent ID should output JSONL with type=error."""
        r = _run_cli_direct(["get", "999999"])
        data = json.loads(r.stdout.strip())
        assert data["type"] == "error"
        assert data["stage"] == "get"


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
    """Commands should exit 1 on failure (via direct invocation)."""

    def test_config_get_invalid_key_exit_1(self) -> None:
        """config get with invalid key should exit 1."""
        exit_code = _run_cli_direct(["config", "get", "nonexistent.key"]).returncode
        assert exit_code == 1
