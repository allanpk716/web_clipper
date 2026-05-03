"""Tests for subcommand --help emitting JSONL instead of Rich text.

Verifies that every subcommand --help invocation produces valid JSONL
output with no Rich markup leaking to stdout.
"""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app


runner = CliRunner()


def _run_help(args: list[str]) -> str:
    """Run web-clip-helper with the given args and return output."""
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.exception}"
    return result.output


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts, stripping ANSI codes."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return [json.loads(line) for line in clean.strip().splitlines() if line.strip()]


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
def test_leaf_help_emits_jsonl(subcmd: str) -> None:
    """Every leaf subcommand --help should emit valid JSONL."""
    output = _run_help([subcmd, "--help"])
    lines = output.strip().splitlines()
    assert len(lines) >= 1, f"Expected at least 1 line of output for {subcmd} --help"

    messages = _parse_jsonl(output)
    assert len(messages) >= 1

    # All messages should have type=help
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1, f"No help message found for {subcmd} --help"

    # Should contain command name
    assert help_msgs[0].get("command") == subcmd
    # Should have description
    assert help_msgs[0].get("description"), f"Missing description for {subcmd}"


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
def test_leaf_help_no_rich_markup(subcmd: str) -> None:
    """No Rich/box-drawing characters should appear in --help output."""
    output = _run_help([subcmd, "--help"])
    # Rich box-drawing chars: ╭ ╮ ╰ ╯ │ ─ ┼ ┤ etc.
    rich_chars = ["╭", "╮", "╰", "╯", "│", "─", "┼", "┤", "┬", "┴", "├", "┝", "┥"]
    for ch in rich_chars:
        assert ch not in output, f"Rich markup char '{ch}' found in {subcmd} --help output"

    # Also check for "Usage:" which is a Rich-format indicator
    assert "Usage:" not in output, f"'Usage:' found in {subcmd} --help output — Rich text leaked"


# ── Nested subcommand --help tests ─────────────────────────────────


def test_config_help_emits_jsonl() -> None:
    """config --help should emit valid JSONL listing subcommands."""
    output = _run_help(["config", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "config"
    # config should list its subcommands (list, get, set, prompt)
    commands = help_msgs[0].get("commands", [])
    cmd_names = [c["name"] for c in commands]
    assert "list" in cmd_names
    assert "get" in cmd_names
    assert "set" in cmd_names
    assert "prompt" in cmd_names


def test_config_prompt_help_emits_jsonl() -> None:
    """config prompt --help should emit valid JSONL."""
    output = _run_help(["config", "prompt", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "config prompt"


def test_config_prompt_test_help_emits_jsonl() -> None:
    """config prompt test --help should emit valid JSONL."""
    output = _run_help(["config", "prompt", "test", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "config prompt test"
    # Should list options like --type, --url, --path
    commands = help_msgs[0].get("commands", [])
    opt_names = [c["name"] for c in commands]
    assert any("--type" in n for n in opt_names)
    assert any("--url" in n for n in opt_names)


# ── Report subcommand --help tests ────────────────────────────────


def test_report_help_emits_jsonl() -> None:
    """report --help should emit valid JSONL."""
    output = _run_help(["report", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "report"
    # report should list its subcommands (submit, list, show)
    commands = help_msgs[0].get("commands", [])
    cmd_names = [c["name"] for c in commands]
    assert "submit" in cmd_names
    assert "list" in cmd_names
    assert "show" in cmd_names


def test_report_submit_help_emits_jsonl() -> None:
    """report submit --help should emit valid JSONL."""
    output = _run_help(["report", "submit", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "report submit"


def test_report_list_help_emits_jsonl() -> None:
    """report list --help should emit valid JSONL."""
    output = _run_help(["report", "list", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "report list"


def test_report_show_help_emits_jsonl() -> None:
    """report show --help should emit valid JSONL."""
    output = _run_help(["report", "show", "--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    assert help_msgs[0].get("command") == "report show"


# ── Root --help test ───────────────────────────────────────────────


def test_root_help_emits_jsonl() -> None:
    """Root --help should still emit valid JSONL (via main callback)."""
    output = _run_help(["--help"])
    messages = _parse_jsonl(output)
    help_msgs = [m for m in messages if m["type"] == "help"]
    assert len(help_msgs) >= 1
    # Root help has no "command" field — just "description" and "commands"
    assert "description" in help_msgs[0]
    assert "commands" in help_msgs[0]
    # Should list all subcommands
    cmd_names = [c["name"] for c in help_msgs[0]["commands"]]
    assert "list" in cmd_names
    assert "clip" in cmd_names
    assert "config" in cmd_names


def test_root_help_no_rich_markup() -> None:
    """Root --help should have no Rich markup."""
    output = _run_help(["--help"])
    rich_chars = ["╭", "╮", "╰", "╯", "│", "─", "┼"]
    for ch in rich_chars:
        assert ch not in output, f"Rich markup char '{ch}' found in root --help output"


# ── All output lines are valid JSON ────────────────────────────────


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
def test_all_lines_valid_jsonl(args: list[str]) -> None:
    """Every line of output should be parseable JSON (no Rich text leaks)."""
    output = _run_help(args)
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            pytest.fail(f"Non-JSON line in {' '.join(args)} output: {line!r}")
        assert "type" in obj, f"Missing 'type' field in JSONL line: {line!r}"
