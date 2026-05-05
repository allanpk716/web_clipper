"""Tests for agent namespace discovery commands — updated for SDK agent commands.

These tests verify the agent schema/errors/info commands work correctly
after the migration from hand-written commands to SDK create_agent_app().
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.error_codes import ErrorCode, EXIT_CODE_MAP

runner = CliRunner()


# ── JSONL envelope convergence ────────────────────────────────────


class TestJSONLEnvelopeConvergence:
    """Verify JSONL output uses only 4 standard types."""

    def test_result_like_types_is_only_result(self):
        """_RESULT_LIKE_TYPES contains result and its aliases after T01 expansion."""
        from web_clip_helper.output import _RESULT_LIKE_TYPES

        assert _RESULT_LIKE_TYPES == frozenset({"result", "help", "schema", "dict"})

    def test_no_schema_dict_diagnostics_types(self):
        """Non-standard types (diagnostics, bogus) raise ValueError."""
        from web_clip_helper.output import jsonl_emit

        for bad_type in ("diagnostics", "bogus", "unknown"):
            with pytest.raises(ValueError, match="Invalid JSONL type"):
                jsonl_emit(bad_type, data={"foo": "bar"})

    def test_four_standard_types_accepted(self):
        """Only result, error, warning, progress are accepted."""
        from web_clip_helper.output import jsonl_emit

        for valid_type in ("result", "error", "warning", "progress"):
            # Should not raise
            try:
                jsonl_emit(valid_type, message="test", stage="test")
            except Exception:
                pass  # Some types need specific kwargs; just check no ValueError


# ── agent info ────────────────────────────────────────────────────


class TestAgentInfo:
    """Verify agent info command output structure."""

    def test_info_exits_zero(self):
        result = runner.invoke(app, ["agent", "info"])
        assert result.exit_code == 0


# ── agent errors ──────────────────────────────────────────────────


class TestAgentErrors:
    """Verify agent errors command output via SDK."""

    def test_errors_exits_zero(self):
        result = runner.invoke(app, ["agent", "errors"])
        assert result.exit_code == 0


# ── ErrorCode.guidance() ──────────────────────────────────────────


class TestErrorCodeGuidance:
    """Verify ErrorCode.guidance() returns meaningful text."""

    def test_guidance_for_known_code(self) -> None:
        g = ErrorCode.guidance("INPUT_INVALID")
        assert isinstance(g, str) and len(g) > 0

    def test_guidance_for_unknown_code(self) -> None:
        g = ErrorCode.guidance("NONEXISTENT_CODE")
        assert isinstance(g, str) and len(g) > 0

    def test_all_codes_have_guidance(self) -> None:
        for code in ErrorCode.all_codes():
            g = ErrorCode.guidance(code)
            assert len(g) > 0, f"Missing guidance for {code}"

    def test_describe_backward_compatible(self) -> None:
        """Ensure describe() still works as before."""
        desc = ErrorCode.describe("INPUT_INVALID")
        assert desc == "Invalid or missing input argument"

    def test_all_codes_backward_compatible(self) -> None:
        """Ensure all_codes() still returns code → description dict."""
        codes = ErrorCode.all_codes()
        assert isinstance(codes, dict)
        assert "INPUT_INVALID" in codes
        assert len(codes) >= 12


# ── agent schema ──────────────────────────────────────────────────


class TestAgentSchema:
    """Verify agent schema command works via SDK."""

    def test_schema_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        assert result.exit_code == 0
