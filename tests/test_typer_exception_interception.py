"""Tests for _JSONLGroup Typer exception interception.

Verifies that all Click/Typer exceptions (missing arguments, invalid options,
missing subcommands) are intercepted by _JSONLGroup and emitted as JSONL
error lines with error_code=INPUT_INVALID instead of Typer's native Rich text.

Every test:
  1. Invokes the CLI via subprocess so _JSONLGroup.main() runs in standalone mode.
  2. Asserts each stdout line is valid JSON (json.loads does not raise).
  3. Asserts type=error and error_code=INPUT_INVALID.
  4. Asserts exit code is correct (typically 2 for Click parameter errors).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Ensure subprocess invocations use the worktree source, not the main repo
# (the editable install .pth points to the main repo).
_WORKTREE_SRC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
_SUBPROCESS_ENV = os.environ.copy()
# Prepend worktree src to PYTHONPATH so it takes priority over .pth
_existing_pp = _SUBPROCESS_ENV.get("PYTHONPATH", "")
_SUBPROCESS_ENV["PYTHONPATH"] = (
    _WORKTREE_SRC + os.pathsep + _existing_pp if _existing_pp else _WORKTREE_SRC
)


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run CLI as subprocess and capture stdout/stderr."""
    return subprocess.run(
        [sys.executable, "-m", "web_clip_helper.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=_SUBPROCESS_ENV,
    )


def _parse_jsonl(stdout: str) -> list[dict]:
    """Parse stdout into a list of JSON objects, one per line."""
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _assert_jsonl_error(process: subprocess.CompletedProcess) -> dict:
    """Assert stdout contains at least one JSONL error with INPUT_INVALID.

    Returns the first matching error dict for further assertions.
    """
    assert process.stdout.strip(), (
        f"Expected JSONL on stdout but got empty output.\n"
        f"stderr: {process.stderr}"
    )
    objs = _parse_jsonl(process.stdout)
    error_lines = [o for o in objs if o.get("type") == "error"]
    assert len(error_lines) >= 1, (
        f"Expected at least one JSONL error line, got: {objs}"
    )
    err = error_lines[0]
    assert err["type"] == "error", f"Expected type=error, got: {err}"
    assert err.get("error_code") == "INPUT_INVALID", (
        f"Expected error_code=INPUT_INVALID, got: {err}"
    )
    return err


# ── Missing required arguments ───────────────────────────────────


class TestMissingArguments:
    """Commands that require arguments should emit JSONL error when args are missing."""

    def test_search_missing_keyword(self) -> None:
        """search without KEYWORD → JSONL error INPUT_INVALID, exit 2."""
        r = _run("search")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2
        assert "KEYWORD" in err["detail"]

    def test_get_missing_id(self) -> None:
        """get without CLIP_ID → JSONL error INPUT_INVALID, exit 2."""
        r = _run("get")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2
        assert "CLIP_ID" in err["detail"] or "ID" in err["detail"]

    def test_delete_missing_id(self) -> None:
        """delete without CLIP_ID → JSONL error INPUT_INVALID, exit 2."""
        r = _run("delete")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2
        assert "CLIP_ID" in err["detail"] or "ID" in err["detail"]

    def test_config_get_missing_key(self) -> None:
        """config get without KEY → JSONL error INPUT_INVALID, exit 2."""
        r = _run("config", "get")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2

    def test_config_set_missing_key(self) -> None:
        """config set without KEY → JSONL error INPUT_INVALID, exit 2."""
        r = _run("config", "set")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2

    def test_config_set_missing_value(self) -> None:
        """config set with KEY but no VALUE → JSONL error INPUT_INVALID, exit 2."""
        r = _run("config", "set", "some.key")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2

    def test_feedback_missing_description(self) -> None:
        """feedback without DESCRIPTION → JSONL error INPUT_INVALID, exit 2."""
        r = _run("feedback")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2


# ── Invalid options ──────────────────────────────────────────────


class TestInvalidOptions:
    """Unknown options should emit JSONL error, not Typer Rich text."""

    def test_clip_unknown_option(self) -> None:
        """clip --nonexistent-option → JSONL error INPUT_INVALID, exit 2."""
        r = _run("clip", "--nonexistent-option")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2
        assert "nonexistent" in err["detail"].lower() or "no such option" in err["detail"].lower()

    def test_search_unknown_option(self) -> None:
        """search --bogus keyword → JSONL error INPUT_INVALID, exit 2."""
        r = _run("search", "--bogus", "test")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2

    def test_list_unknown_option(self) -> None:
        """list --invalid-flag → JSONL error INPUT_INVALID, exit 2."""
        r = _run("list", "--invalid-flag")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2

    def test_global_unknown_option(self) -> None:
        """Global unknown option → JSONL error INPUT_INVALID, exit 2."""
        r = _run("--nonexistent-global-flag")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2


# ── Missing subcommand ───────────────────────────────────────────


class TestMissingSubcommand:
    """Groups that require subcommands should emit JSONL error."""

    def test_config_no_subcommand(self) -> None:
        """config (no subcommand) → JSONL error INPUT_INVALID (NoArgsIsHelpError)."""
        r = _run("config")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2

    def test_config_prompt_no_subcommand(self) -> None:
        """config prompt (no subcommand) → JSONL error INPUT_INVALID."""
        r = _run("config", "prompt")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2


# ── Nested subcommand missing required options ───────────────────


class TestNestedSubcommandMissingOptions:
    """config prompt test requires --type and --url; missing either → JSONL error."""

    def test_prompt_test_missing_type(self) -> None:
        """config prompt test without --type → JSONL error INPUT_INVALID, exit 2."""
        r = _run("config", "prompt", "test", "--url", "https://example.com")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2
        assert "--type" in err["detail"]

    def test_prompt_test_missing_url(self) -> None:
        """config prompt test without --url → JSONL error INPUT_INVALID, exit 2."""
        r = _run("config", "prompt", "test", "--type", "title")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2
        assert "--url" in err["detail"]

    def test_prompt_test_missing_both(self) -> None:
        """config prompt test without --type or --url → JSONL error INPUT_INVALID, exit 2."""
        r = _run("config", "prompt", "test")
        err = _assert_jsonl_error(r)
        assert r.returncode == 2


# ── JSONL purity: every stdout line must be valid JSON ────────────


class TestJSONLPurity:
    """Verify stdout contains only valid JSON lines — no Rich text, no ANSI noise."""

    def test_search_missing_args_pure_jsonl(self) -> None:
        """Every line of stdout from a failing search must be valid JSON."""
        r = _run("search")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = []
        for line in lines:
            obj = json.loads(line)  # must not raise
            parsed.append(obj)
        assert any(o.get("type") == "error" for o in parsed)

    def test_get_missing_args_pure_jsonl(self) -> None:
        """Every line of stdout from a failing get must be valid JSON."""
        r = _run("get")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)

    def test_clip_bad_option_pure_jsonl(self) -> None:
        """Every line of stdout from clip with bad option must be valid JSON."""
        r = _run("clip", "--bad-opt")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)

    def test_no_rich_text_in_error_output(self) -> None:
        """Error output must not contain Rich markup markers or Typer Usage: headers."""
        r = _run("search")
        stdout = r.stdout.lower()
        assert "[bold]" not in stdout
        assert "[red]" not in stdout
        assert "[error]" not in stdout
        # Typer's default "Usage:" header should NOT appear — we intercept it
        assert "usage:" not in stdout

    def test_config_no_subcommand_pure_jsonl(self) -> None:
        """config without subcommand: stdout is pure JSONL (no Rich table)."""
        r = _run("config")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)

    def test_config_prompt_test_missing_opts_pure_jsonl(self) -> None:
        """config prompt test without required opts: stdout is pure JSONL."""
        r = _run("config", "prompt", "test")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)
