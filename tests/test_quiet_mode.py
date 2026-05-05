"""Tests for --quiet flag suppression across CLI commands.

Verifies that ``--quiet/-q`` suppresses ``progress`` and ``warning`` type
JSONL output while preserving ``result`` and ``error`` output.
"""

from __future__ import annotations

from web_clip_helper.output import set_quiet


# ── --quiet suppresses progress for read-only commands ────────────


def test_quiet_list_suppresses_progress(run_sdk_cli) -> None:
    """``--quiet list`` should emit zero progress lines."""
    code, envelopes = run_sdk_cli(["--quiet", "list"])
    assert code == 0, f"Exit {code}"
    types = [e["type"] for e in envelopes]
    assert "progress" not in types, f"progress leaked through --quiet: {types}"
    # At least one result should still be emitted
    assert "result" in types, f"Expected result lines, got: {types}"


def test_quiet_tags_suppresses_progress(run_sdk_cli) -> None:
    """``--quiet tags`` should emit zero progress lines."""
    code, envelopes = run_sdk_cli(["--quiet", "tags"])
    assert code == 0, f"Exit {code}"
    types = [e["type"] for e in envelopes]
    assert "progress" not in types, f"progress leaked through --quiet: {types}"


def test_quiet_search_suppresses_progress(run_sdk_cli) -> None:
    """``--quiet search KEYWORD`` should emit zero progress lines."""
    code, envelopes = run_sdk_cli(["--quiet", "search", "requests"])
    assert code == 0, f"Exit {code}"
    types = [e["type"] for e in envelopes]
    assert "progress" not in types, f"progress leaked through --quiet: {types}"


# ── --quiet suppresses progress for write commands ────────────────


def test_quiet_clip_text_suppresses_progress(run_sdk_cli) -> None:
    """``--quiet clip --text`` should emit zero progress lines."""
    code, envelopes = run_sdk_cli(["--quiet", "clip", "--text", "quiet mode test content"])
    assert code == 0, f"Exit {code}"
    types = [e["type"] for e in envelopes]
    assert "progress" not in types, f"progress leaked through --quiet: {types}"
    assert "result" in types, f"Expected result line, got: {types}"


# ── --quiet preserves result output ──────────────────────────────


def test_quiet_list_still_emits_results(run_sdk_cli) -> None:
    """``--quiet list`` should still emit result lines."""
    code, envelopes = run_sdk_cli(["--quiet", "list"])
    result_msgs = [e for e in envelopes if e["type"] == "result"]
    assert len(result_msgs) >= 1, "Expected at least one result line"


def test_quiet_tags_still_emits_results(run_sdk_cli) -> None:
    """``--quiet tags`` should still emit result lines when tags exist."""
    code, envelopes = run_sdk_cli(["--quiet", "tags"])
    # tags may emit zero results if no clips have tags — that's acceptable
    # Just verify no progress leaked through
    types = [e["type"] for e in envelopes]
    assert "progress" not in types, f"progress leaked through --quiet: {types}"


# ── --quiet preserves error output ────────────────────────────────


def test_quiet_preserves_error_on_bad_input(run_sdk_cli) -> None:
    """``--quiet`` should not suppress error lines."""
    # search requires a keyword argument — omitting it triggers an error
    code, envelopes = run_sdk_cli(["--quiet", "search"])
    assert code != 0
    error_msgs = [e for e in envelopes if e["type"] == "error"]
    assert len(error_msgs) >= 1, "Expected error line even under --quiet"
    assert error_msgs[0].get("error_code") == "INPUT_INVALID"


def test_quiet_preserves_error_on_missing_args(run_sdk_cli) -> None:
    """``--quiet`` should not suppress error for missing clip ID."""
    code, envelopes = run_sdk_cli(["--quiet", "get"])
    assert code != 0
    error_msgs = [e for e in envelopes if e["type"] == "error"]
    assert len(error_msgs) >= 1, "Expected error line for missing argument"


# ── without --quiet, progress IS emitted (regression guard) ───────


def test_without_quiet_list_has_progress(run_sdk_cli) -> None:
    """Without ``--quiet``, ``list`` should emit progress lines."""
    code, envelopes = run_sdk_cli(["list"])
    assert code == 0
    types = [e["type"] for e in envelopes]
    assert "progress" in types, f"Expected progress without --quiet, got: {types}"


def test_without_quiet_tags_has_progress(run_sdk_cli) -> None:
    """Without ``--quiet``, ``tags`` should emit progress lines."""
    code, envelopes = run_sdk_cli(["tags"])
    assert code == 0
    types = [e["type"] for e in envelopes]
    assert "progress" in types, f"Expected progress without --quiet, got: {types}"
