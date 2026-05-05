"""Tests for subcommand --help emitting SDK Envelope JSONL.

Verifies that every subcommand --help invocation produces valid SDK Envelope
JSONL output with type=result and commands in data.commands.
"""

from __future__ import annotations

import json
import re

import pytest

from tests.conftest import _parse_envelopes, _unwrap_data


# ── Helpers ─────────────────────────────────────────────────────────


def _strip_ansi(output: str) -> str:
    """Strip ANSI escape codes."""
    return re.sub(r"\x1b\[[0-9;]*m", "", output)


# ── Leaf command --help tests ──────────────────────────────────────


@pytest.mark.parametrize("subcmd", [
    "list",
    "get",
    "search",
    "clip",
    "delete",
    "update",
    "refresh",
    "tags",
    "version",
])
def test_leaf_help_emits_valid_envelope(run_sdk_cli, subcmd: str) -> None:
    """Every leaf subcommand --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli([subcmd, "--help"])
    assert code == 0
    assert len(envelopes) >= 1
    # Help is now type=result with commands in data
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1
    data = _unwrap_data(results[0])
    assert "commands" in data
    assert "description" in data


@pytest.mark.parametrize("subcmd", [
    "list",
    "get",
    "search",
    "clip",
    "delete",
    "update",
    "refresh",
    "tags",
    "version",
])
def test_leaf_help_no_rich_markup(run_sdk_cli, subcmd: str) -> None:
    """No Rich/box-drawing characters should appear in --help output."""
    code, envelopes = run_sdk_cli([subcmd, "--help"])
    assert code == 0
    # Rich box-drawing chars should not appear in any envelope field
    rich_chars = ["╭", "╮", "╰", "╯", "│", "─", "┼", "┤", "┬", "┴", "├", "┝", "┥"]
    for env in envelopes:
        env_str = json.dumps(env)
        for ch in rich_chars:
            assert ch not in env_str, f"Rich markup char '{ch}' found in {subcmd} --help"


# ── Nested subcommand --help tests ─────────────────────────────────


def test_config_help_emits_envelope(run_sdk_cli) -> None:
    """config --help should emit valid SDK Envelope JSONL listing subcommands."""
    code, envelopes = run_sdk_cli(["config", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1
    data = _unwrap_data(results[0])
    commands = data.get("commands", [])
    cmd_names = [c["name"] for c in commands]
    # Root help lists all top-level commands including config
    assert "config" in cmd_names


def test_config_prompt_help_emits_envelope(run_sdk_cli) -> None:
    """config prompt --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["config", "prompt", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1


def test_config_prompt_test_help_emits_envelope(run_sdk_cli) -> None:
    """config prompt test --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["config", "prompt", "test", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1


# ── Report subcommand --help tests ────────────────────────────────


def test_report_help_emits_envelope(run_sdk_cli) -> None:
    """report --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["report", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1


def test_report_submit_help_emits_envelope(run_sdk_cli) -> None:
    """report submit --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["report", "submit", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1


def test_report_list_help_emits_envelope(run_sdk_cli) -> None:
    """report list --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["report", "list", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1


def test_report_show_help_emits_envelope(run_sdk_cli) -> None:
    """report show --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["report", "show", "--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1


# ── Root --help test ───────────────────────────────────────────────


def test_root_help_emits_envelope(run_sdk_cli) -> None:
    """Root --help should emit valid SDK Envelope JSONL."""
    code, envelopes = run_sdk_cli(["--help"])
    assert code == 0
    results = [e for e in envelopes if e["type"] == "result"]
    assert len(results) >= 1
    data = _unwrap_data(results[0])
    assert "commands" in data
    assert "description" in data
    cmd_names = [c["name"] for c in data["commands"]]
    assert "list" in cmd_names
    assert "clip" in cmd_names
    assert "config" in cmd_names


def test_root_help_no_rich_markup(run_sdk_cli) -> None:
    """Root --help should have no Rich markup."""
    code, envelopes = run_sdk_cli(["--help"])
    assert code == 0
    rich_chars = ["╭", "╮", "╰", "╯", "│", "─", "┼"]
    for env in envelopes:
        env_str = json.dumps(env)
        for ch in rich_chars:
            assert ch not in env_str, f"Rich markup char '{ch}' found in root --help"


# ── All output lines are valid SDK Envelopes ───────────────────────


@pytest.mark.parametrize("args", [
    ["list", "--help"],
    ["get", "--help"],
    ["search", "--help"],
    ["clip", "--help"],
    ["config", "--help"],
    ["config", "prompt", "--help"],
    ["config", "prompt", "test", "--help"],
    ["--help"],
])
def test_all_lines_valid_envelope_jsonl(run_sdk_cli, args: list[str]) -> None:
    """Every line of output should be a valid SDK Envelope."""
    code, envelopes = run_sdk_cli(args)
    assert code == 0
    assert len(envelopes) >= 1
    # _parse_envelopes already validates envelope structure
    for env in envelopes:
        assert "type" in env
