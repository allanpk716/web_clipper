"""Tests for --quiet flag suppression across CLI commands.

Verifies that ``--quiet/-q`` suppresses ``progress`` and ``warning`` type
JSONL output while preserving ``result`` and ``error`` output.
"""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.output import set_quiet

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_quiet():
    """Ensure ``_quiet_mode`` is reset before and after every test."""
    set_quiet(False)
    yield
    set_quiet(False)


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts, stripping ANSI codes."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return [json.loads(line) for line in clean.strip().splitlines() if line.strip()]


def _collect_types(output: str) -> list[str]:
    """Extract ``type`` field from each JSONL line."""
    return [m["type"] for m in _parse_jsonl(output)]


# ── --quiet suppresses progress for read-only commands ────────────


def test_quiet_list_suppresses_progress() -> None:
    """``--quiet list`` should emit zero progress lines."""
    result = runner.invoke(app, ["--quiet", "list"])
    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"
    types = _collect_types(result.output)
    assert "progress" not in types, f"progress leaked through --quiet: {types}"
    # At least one result should still be emitted
    assert "result" in types, f"Expected result lines, got: {types}"


def test_quiet_tags_suppresses_progress() -> None:
    """``--quiet tags`` should emit zero progress lines."""
    result = runner.invoke(app, ["--quiet", "tags"])
    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"
    types = _collect_types(result.output)
    assert "progress" not in types, f"progress leaked through --quiet: {types}"


def test_quiet_search_suppresses_progress() -> None:
    """``--quiet search KEYWORD`` should emit zero progress lines."""
    result = runner.invoke(app, ["--quiet", "search", "requests"])
    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"
    types = _collect_types(result.output)
    assert "progress" not in types, f"progress leaked through --quiet: {types}"


# ── --quiet suppresses progress for write commands ────────────────


def test_quiet_clip_text_suppresses_progress() -> None:
    """``--quiet clip --text`` should emit zero progress lines."""
    result = runner.invoke(app, ["--quiet", "clip", "--text", "quiet mode test content"])
    assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"
    types = _collect_types(result.output)
    assert "progress" not in types, f"progress leaked through --quiet: {types}"
    assert "result" in types, f"Expected result line, got: {types}"


# ─-- --quiet preserves result output ──────────────────────────────


def test_quiet_list_still_emits_results() -> None:
    """``--quiet list`` should still emit result lines."""
    result = runner.invoke(app, ["--quiet", "list"])
    messages = _parse_jsonl(result.output)
    result_msgs = [m for m in messages if m["type"] == "result"]
    assert len(result_msgs) >= 1, "Expected at least one result line"


def test_quiet_tags_still_emits_results() -> None:
    """``--quiet tags`` should still emit result lines."""
    result = runner.invoke(app, ["--quiet", "tags"])
    messages = _parse_jsonl(result.output)
    result_msgs = [m for m in messages if m["type"] == "result"]
    assert len(result_msgs) >= 1, "Expected at least one result line"


# ── --quiet preserves error output ────────────────────────────────


def test_quiet_preserves_error_on_bad_input() -> None:
    """``--quiet`` should not suppress error lines."""
    # search requires a keyword argument — omitting it triggers an error
    result = runner.invoke(app, ["--quiet", "search"])
    assert result.exit_code != 0
    messages = _parse_jsonl(result.output)
    error_msgs = [m for m in messages if m["type"] == "error"]
    assert len(error_msgs) >= 1, "Expected error line even under --quiet"
    assert error_msgs[0].get("error_code") == "INPUT_INVALID"


def test_quiet_preserves_error_on_missing_args() -> None:
    """``--quiet`` should not suppress error for missing clip ID."""
    result = runner.invoke(app, ["--quiet", "get"])
    assert result.exit_code != 0
    messages = _parse_jsonl(result.output)
    error_msgs = [m for m in messages if m["type"] == "error"]
    assert len(error_msgs) >= 1, "Expected error line for missing argument"


# ── without --quiet, progress IS emitted (regression guard) ───────


def test_without_quiet_list_has_progress() -> None:
    """Without ``--quiet``, ``list`` should emit progress lines."""
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    types = _collect_types(result.output)
    assert "progress" in types, f"Expected progress without --quiet, got: {types}"


def test_without_quiet_tags_has_progress() -> None:
    """Without ``--quiet``, ``tags`` should emit progress lines."""
    result = runner.invoke(app, ["tags"])
    assert result.exit_code == 0
    types = _collect_types(result.output)
    assert "progress" in types, f"Expected progress without --quiet, got: {types}"
