"""Tests for _SDKGroup Typer exception interception.

Verifies that all Click/Typer exceptions (missing arguments, invalid options,
missing subcommands) are intercepted by _SDKGroup and emitted as SDK Envelope
JSONL error lines with error_code=INPUT_INVALID.

Every test:
  1. Invokes the CLI via subprocess so App.run() runs in standalone mode.
  2. Asserts each stdout line is valid SDK Envelope JSON.
  3. Asserts type=error and error_code=INPUT_INVALID.
  4. Asserts exit code matches the expected semantic code.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run CLI as subprocess and capture stdout/stderr."""
    return subprocess.run(
        [sys.executable, "-m", "web_clip_helper.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def _parse_envelopes(stdout: str) -> list[dict]:
    """Parse stdout into a list of SDK Envelope JSON objects."""
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    envelopes = []
    for line in lines:
        obj = json.loads(line)
        for field in ("version", "tool", "type", "timestamp"):
            assert field in obj, f"Envelope missing required field {field!r}: {line}"
        envelopes.append(obj)
    return envelopes


def _assert_envelope_error(process: subprocess.CompletedProcess) -> dict:
    """Assert stdout contains at least one SDK Envelope error with INPUT_INVALID.

    Returns the first matching error dict for further assertions.
    """
    assert process.stdout.strip(), (
        f"Expected JSONL on stdout but got empty output.\n"
        f"stderr: {process.stderr}"
    )
    envelopes = _parse_envelopes(process.stdout)
    error_lines = [o for o in envelopes if o.get("type") == "error"]
    assert len(error_lines) >= 1, (
        f"Expected at least one error envelope, got: {envelopes}"
    )
    err = error_lines[0]
    assert err["type"] == "error", f"Expected type=error, got: {err}"
    assert err.get("error_code") == "INPUT_INVALID", (
        f"Expected error_code=INPUT_INVALID, got: {err}"
    )
    return err


# ── Missing required arguments ───────────────────────────────────


class TestMissingArguments:
    """Commands that require arguments should emit envelope error when args are missing."""

    def test_search_missing_keyword(self) -> None:
        """search without KEYWORD → envelope error INPUT_INVALID, exit 2."""
        r = _run("search")
        err = _assert_envelope_error(r)
        assert r.returncode == 2
        msg = err.get("message", "")
        assert "KEYWORD" in msg

    def test_get_missing_id(self) -> None:
        """get without CLIP_ID → envelope error INPUT_INVALID, exit 2."""
        r = _run("get")
        err = _assert_envelope_error(r)
        assert r.returncode == 2
        msg = err.get("message", "")
        assert "CLIP_ID" in msg or "ID" in msg

    def test_delete_missing_id(self) -> None:
        """delete without CLIP_ID → envelope error INPUT_INVALID, exit 2."""
        r = _run("delete")
        err = _assert_envelope_error(r)
        assert r.returncode == 2
        msg = err.get("message", "")
        assert "CLIP_ID" in msg or "ID" in msg

    def test_config_get_missing_key(self) -> None:
        """config get without KEY → envelope error INPUT_INVALID, exit 2."""
        r = _run("config", "get")
        err = _assert_envelope_error(r)
        assert r.returncode == 2

    def test_config_set_missing_key(self) -> None:
        """config set without KEY → envelope error INPUT_INVALID, exit 2."""
        r = _run("config", "set")
        err = _assert_envelope_error(r)
        assert r.returncode == 2

    def test_config_set_missing_value(self) -> None:
        """config set with KEY but no VALUE → envelope error INPUT_INVALID, exit 2."""
        r = _run("config", "set", "some.key")
        err = _assert_envelope_error(r)
        assert r.returncode == 2

    def test_feedback_missing_description(self) -> None:
        """feedback without DESCRIPTION → envelope error INPUT_INVALID, exit 2."""
        r = _run("feedback")
        err = _assert_envelope_error(r)
        assert r.returncode == 2


# ── Invalid options ──────────────────────────────────────────────


class TestInvalidOptions:
    """Unknown options should emit envelope error, not Typer Rich text."""

    def test_clip_unknown_option(self) -> None:
        """clip --nonexistent-option → envelope error INPUT_INVALID, exit 2."""
        r = _run("clip", "--nonexistent-option")
        err = _assert_envelope_error(r)
        assert r.returncode == 2
        msg = err.get("message", "").lower()
        assert "nonexistent" in msg or "no such option" in msg

    def test_search_unknown_option(self) -> None:
        """search --bogus keyword → envelope error INPUT_INVALID, exit 2."""
        r = _run("search", "--bogus", "test")
        err = _assert_envelope_error(r)
        assert r.returncode == 2

    def test_list_unknown_option(self) -> None:
        """list --invalid-flag → envelope error INPUT_INVALID, exit 2."""
        r = _run("list", "--invalid-flag")
        err = _assert_envelope_error(r)
        assert r.returncode == 2

    def test_global_unknown_option(self) -> None:
        """Global unknown option → envelope error INPUT_INVALID, exit 2."""
        r = _run("--nonexistent-global-flag")
        err = _assert_envelope_error(r)
        assert r.returncode == 2


# ── Missing subcommand ───────────────────────────────────────────


class TestMissingSubcommand:
    """Groups that require subcommands should emit envelope error."""

    def test_config_no_subcommand(self) -> None:
        """config (no subcommand) → envelope error INPUT_INVALID."""
        r = _run("config")
        err = _assert_envelope_error(r)
        assert r.returncode == 2

    def test_config_prompt_no_subcommand(self) -> None:
        """config prompt (no subcommand) → envelope error INPUT_INVALID."""
        r = _run("config", "prompt")
        err = _assert_envelope_error(r)
        assert r.returncode == 2


# ── Nested subcommand missing required options ───────────────────


class TestNestedSubcommandMissingOptions:
    """config prompt test requires --type and --url; missing either → envelope error."""

    def test_prompt_test_missing_type(self) -> None:
        """config prompt test without --type → envelope error INPUT_INVALID, exit 2."""
        r = _run("config", "prompt", "test", "--url", "https://example.com")
        err = _assert_envelope_error(r)
        assert r.returncode == 2
        msg = err.get("message", "")
        assert "--type" in msg

    def test_prompt_test_missing_url(self) -> None:
        """config prompt test without --url → envelope error INPUT_INVALID, exit 2."""
        r = _run("config", "prompt", "test", "--type", "title")
        err = _assert_envelope_error(r)
        assert r.returncode == 2
        msg = err.get("message", "")
        assert "--url" in msg

    def test_prompt_test_missing_both(self) -> None:
        """config prompt test without --type or --url → envelope error INPUT_INVALID, exit 2."""
        r = _run("config", "prompt", "test")
        err = _assert_envelope_error(r)
        assert r.returncode == 2


# ── JSONL purity: every stdout line must be valid SDK Envelope ────


class TestJSONLPurity:
    """Verify stdout contains only valid SDK Envelope lines — no Rich text, no ANSI noise."""

    def test_search_missing_args_pure_jsonl(self) -> None:
        """Every line of stdout from a failing search must be valid SDK Envelope."""
        r = _run("search")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = []
        for line in lines:
            obj = json.loads(line)  # must not raise
            parsed.append(obj)
        assert any(o.get("type") == "error" for o in parsed)

    def test_get_missing_args_pure_jsonl(self) -> None:
        """Every line of stdout from a failing get must be valid SDK Envelope."""
        r = _run("get")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)

    def test_clip_bad_option_pure_jsonl(self) -> None:
        """Every line of stdout from clip with bad option must be valid SDK Envelope."""
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
        """config without subcommand: stdout is pure SDK Envelope JSONL."""
        r = _run("config")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)

    def test_config_prompt_test_missing_opts_pure_jsonl(self) -> None:
        """config prompt test without required opts: stdout is pure SDK Envelope."""
        r = _run("config", "prompt", "test")
        assert r.returncode != 0
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        parsed = [json.loads(l) for l in lines]
        assert any(o.get("type") == "error" for o in parsed)
