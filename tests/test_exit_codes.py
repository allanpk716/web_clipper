"""Tests verifying exit code conventions: 0 for success, 1 for failure.

Note: When invoked via `python -m web_clip_helper.cli`, Typer's
`invoke_without_command=True` callback may absorb Exit(1) from subcommands.
Direct invocation (setting sys.argv + calling app()) correctly propagates exit codes.
The tests here use subprocess for integration-level verification where possible,
and document known Typer behaviors.
"""

from __future__ import annotations

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


def _run_cli_direct(args: list[str]) -> int:
    """Run CLI via direct app() call and return the exit code."""
    result = subprocess.run(
        [
            sys.executable, "-c",
            f"import sys; sys.argv = {['test'] + args}; "
            "from web_clip_helper.cli import app; app()",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode


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

    def test_get_nonexistent_exit_1(self) -> None:
        """get command with invalid ID should exit 1."""
        exit_code = _run_cli_direct(["get", "999999"])
        assert exit_code == 1

    def test_config_get_invalid_key_exit_1(self) -> None:
        """config get with invalid key should exit 1."""
        exit_code = _run_cli_direct(["config", "get", "nonexistent.key"])
        assert exit_code == 1
