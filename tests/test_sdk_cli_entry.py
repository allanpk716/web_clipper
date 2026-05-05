"""Tests for CLI entry point refactored to use SDK App.run().

Verifies that:
- main() delegates to SDK App.run()
- clip command through main() produces SDK Envelope JSONL
- --quiet suppresses progress
- Missing URL produces INPUT_INVALID JSONL error
- ClickException (bad option) produces INPUT_INVALID JSONL error
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_app_singleton():
    """Reset the App singleton between tests."""
    import web_clip_helper.app as mod
    mod._app = None
    yield
    mod._app = None


@pytest.fixture()
def run_cli():
    """Run the CLI via SDK App.run() and return (exit_code, jsonl_output).

    Captures the real stdout that SDK Writer targets by replacing
    sys.stdout *before* App initialization so the SDK stores our
    StringIO as _real_stdout.
    """
    def _run(args: list[str], env: dict | None = None) -> tuple[int, str]:
        import web_clip_helper.app as app_mod
        from web_clip_helper.cli import app as typer_app

        # Capture real stdout — must be set BEFORE App is created,
        # because App.__init__ saves sys.stdout as self._real_stdout.
        real_stdout = io.StringIO()
        saved_stdout = sys.stdout
        sys.stdout = real_stdout

        # Reset singleton so App picks up our real_stdout
        app_mod._app = None

        old_exit = sys.exit
        exit_codes: list[int] = []
        sys.exit = lambda code=0: exit_codes.append(code)  # type: ignore[assignment]

        old_env = os.environ.copy()
        if env:
            for k, v in env.items():
                os.environ[k] = v

        try:
            sdk_app = app_mod.get_app()
            code = sdk_app.run(typer_app, args=args)
            if exit_codes:
                code = exit_codes[-1]
            output = real_stdout.getvalue()
            return code, output
        finally:
            sys.stdout = saved_stdout
            sys.exit = old_exit
            for k in list(os.environ.keys()):
                if k not in old_env:
                    del os.environ[k]
                elif os.environ[k] != old_env[k]:
                    os.environ[k] = old_env[k]
            for k in set(old_env.keys()) - set(os.environ.keys()):
                os.environ[k] = old_env[k]

    return _run


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    lines = [l for l in output.strip().split("\n") if l.strip()]
    return [json.loads(line) for line in lines]


# ── main() delegates to App.run() ────────────────────────────────


class TestMainDelegation:
    """main() invokes SDK App.run()."""

    def test_main_returns_exit_code(self, run_cli):
        """Version command returns exit code 0 via SDK App.run()."""
        code, output = run_cli(["version"])
        assert code == 0

    def test_main_produces_jsonl(self, run_cli):
        """Output from main() is valid JSONL envelope."""
        code, output = run_cli(["version"])
        assert output.strip()
        objs = _parse_jsonl(output)
        assert len(objs) >= 1
        obj = objs[0]
        assert "tool" in obj
        assert "version" in obj
        assert "timestamp" in obj

    def test_trace_id_from_env(self, run_cli):
        """SDK App.run() reads AGENT_TRACE_ID from environment."""
        code, output = run_cli(["version"], env={"AGENT_TRACE_ID": "test-trace-42"})
        objs = _parse_jsonl(output)
        assert len(objs) >= 1
        assert objs[0].get("trace_id") == "test-trace-42"


# ── Clip command produces SDK Envelope JSONL ─────────────────────


class TestClipEnvelopeOutput:
    """clip command through main() produces SDK Envelope JSONL."""

    def test_missing_url_produces_input_invalid_error(self, run_cli):
        """Missing URL argument produces INPUT_INVALID JSONL error."""
        code, output = run_cli(["clip"])
        assert code != 0
        objs = _parse_jsonl(output)
        error_objs = [o for o in objs if o.get("type") == "error"]
        assert len(error_objs) >= 1
        err = error_objs[0]
        assert err["error_code"] == "INPUT_INVALID"

    def test_clip_missing_url_exit_code(self, run_cli):
        """Missing URL exits with INPUT_INVALID exit code (2)."""
        code, output = run_cli(["clip"])
        assert code == 2


# ── --quiet mode ─────────────────────────────────────────────────


class TestQuietMode:
    """--quiet flag suppresses progress and warning output."""

    def test_quiet_suppresses_progress(self, run_cli):
        """With --quiet, no progress lines appear in output."""
        code, output = run_cli(["--quiet", "version"])
        objs = _parse_jsonl(output)
        progress = [o for o in objs if o.get("type") == "progress"]
        assert len(progress) == 0

    def test_quiet_preserves_result(self, run_cli):
        """With --quiet, result lines still appear."""
        code, output = run_cli(["--quiet", "version"])
        objs = _parse_jsonl(output)
        results = [o for o in objs if o.get("type") == "result"]
        assert len(results) >= 1
        ver = results[0]
        assert "version" in ver.get("data", {})


# ── ClickException handling ──────────────────────────────────────


class TestClickExceptionHandling:
    """Bad CLI options produce INPUT_INVALID JSONL errors."""

    def test_bad_option_produces_input_invalid(self, run_cli):
        """Unknown option produces INPUT_INVALID JSONL error."""
        code, output = run_cli(["--nonexistent-flag"])
        assert code != 0
        objs = _parse_jsonl(output)
        error_objs = [o for o in objs if o.get("type") == "error"]
        assert len(error_objs) >= 1
        assert error_objs[0]["error_code"] == "INPUT_INVALID"

    def test_bad_subcommand_option_produces_input_invalid(self, run_cli):
        """Bad option on subcommand produces INPUT_INVALID JSONL error."""
        code, output = run_cli(["clip", "--bogus-option"])
        assert code != 0
        objs = _parse_jsonl(output)
        error_objs = [o for o in objs if o.get("type") == "error"]
        assert len(error_objs) >= 1
        assert error_objs[0]["error_code"] == "INPUT_INVALID"


# ── Help output ──────────────────────────────────────────────────


class TestHelpOutput:
    """--help produces JSONL help output."""

    def test_help_produces_result_envelope(self, run_cli):
        """Root --help produces JSONL result with commands."""
        code, output = run_cli(["--help"])
        assert code == 0
        objs = _parse_jsonl(output)
        results = [o for o in objs if o.get("type") == "result"]
        assert len(results) >= 1
        data = results[0].get("data", {})
        assert "commands" in data

    def test_no_args_produces_help(self, run_cli):
        """No arguments produces JSONL help (like --help)."""
        code, output = run_cli([])
        assert code == 0
        objs = _parse_jsonl(output)
        results = [o for o in objs if o.get("type") == "result"]
        assert len(results) >= 1
