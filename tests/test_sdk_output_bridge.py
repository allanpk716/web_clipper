"""Tests for output.py → SDK Writer bridge.

Verifies that all jsonl_emit* functions produce valid SDK Envelope JSONL
through the agentsdk Writer, including quiet mode suppression, trace_id
injection, and correct error_code encoding.
"""

from __future__ import annotations

import io
import json

import pytest

from web_clip_helper.app import get_app
from web_clip_helper.output import (
    jsonl_emit,
    jsonl_emit_dict,
    jsonl_emit_error,
    jsonl_emit_help,
    jsonl_emit_progress,
    jsonl_emit_result,
    jsonl_emit_schema,
    jsonl_emit_warning,
    set_quiet,
    set_trace_id,
    get_trace_id,
)
from agentsdk.writer import Writer


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_app():
    """Reset the App singleton and inject a test Writer for each test."""
    import web_clip_helper.app as mod
    mod._app = None

    # Create a fresh App and inject a Writer targeting a StringIO we own.
    app = get_app()
    buf = io.StringIO()
    test_writer = Writer(buf, tool_name="web-clip-helper")
    app.set_writer(test_writer)

    yield

    mod._app = None


def _get_writer_buf() -> io.StringIO:
    """Return the StringIO buffer attached to the current test Writer."""
    app = get_app()
    return app.writer._output


def _read_lines() -> list[str]:
    """Read all JSONL lines written so far, stripping trailing newlines."""
    buf = _get_writer_buf()
    text = buf.getvalue()
    if not text.strip():
        return []
    return [line for line in text.strip().split("\n") if line.strip()]


def _parse_lines() -> list[dict]:
    """Parse all JSONL lines written so far into dicts."""
    return [json.loads(line) for line in _read_lines()]


def _parse_single() -> dict:
    """Parse exactly one JSONL line (fails if != 1)."""
    lines = _parse_lines()
    assert len(lines) == 1, f"Expected 1 line, got {len(lines)}"
    return lines[0]


# ── Core jsonl_emit ──────────────────────────────────────────────


class TestJsonlEmitEnvelope:
    """jsonl_emit produces valid SDK Envelope JSONL."""

    def test_progress_envelope(self) -> None:
        jsonl_emit("progress", message="working", percent=42)
        obj = _parse_single()
        assert obj["type"] == "progress"
        assert obj["message"] == "working"
        assert obj["percent"] == 42
        assert obj["tool"] == "web-clip-helper"
        assert "version" in obj
        assert "timestamp" in obj

    def test_result_envelope(self) -> None:
        jsonl_emit("result", url="https://example.com", status="ok")
        obj = _parse_single()
        assert obj["type"] == "result"
        # SDK Writer wraps kwargs inside "data"
        assert obj["data"]["url"] == "https://example.com"
        assert obj["data"]["status"] == "ok"

    def test_error_envelope_without_code(self) -> None:
        jsonl_emit("error", stage="fetch", detail="timeout")
        obj = _parse_single()
        assert obj["type"] == "error"
        # stage and detail encoded in message as [stage] detail
        assert obj["message"] == "[fetch] timeout"
        # SDK defaults to "error" code when no explicit code
        assert obj["error_code"] == "error"

    def test_error_envelope_with_code(self) -> None:
        jsonl_emit("error", stage="clip", detail="bad url", error_code="INPUT_INVALID")
        obj = _parse_single()
        assert obj["type"] == "error"
        assert obj["error_code"] == "INPUT_INVALID"
        assert obj["message"] == "[clip] bad url"

    def test_warning_envelope(self) -> None:
        jsonl_emit("warning", message="slow network")
        obj = _parse_single()
        assert obj["type"] == "warning"
        assert obj["message"] == "slow network"

    def test_help_maps_to_result_type(self) -> None:
        jsonl_emit("help", commands=[{"name": "clip", "help": "Clip a URL"}])
        obj = _parse_single()
        assert obj["type"] == "result"
        assert obj["data"]["commands"] == [{"name": "clip", "help": "Clip a URL"}]

    def test_schema_maps_to_result_type(self) -> None:
        jsonl_emit("schema", data={"fields": ["url", "format"]})
        obj = _parse_single()
        assert obj["type"] == "result"
        assert obj["data"]["data"] == {"fields": ["url", "format"]}

    def test_dict_maps_to_result_type(self) -> None:
        jsonl_emit("dict", data={"codes": ["E001", "E002"]})
        obj = _parse_single()
        assert obj["type"] == "result"
        assert obj["data"]["data"] == {"codes": ["E001", "E002"]}

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSONL type"):
            jsonl_emit("bogus")

    def test_multiple_emits(self) -> None:
        jsonl_emit("progress", message="step1")
        jsonl_emit("progress", message="step2")
        jsonl_emit("result", done=True)
        objs = _parse_lines()
        assert len(objs) == 3
        types = [o["type"] for o in objs]
        assert types == ["progress", "progress", "result"]


# ── Convenience wrappers ─────────────────────────────────────────


class TestConvenienceWrappers:
    """Convenience functions delegate correctly to jsonl_emit."""

    def test_emit_error_with_code(self) -> None:
        jsonl_emit_error(stage="fetch", detail="timeout", error_code="FETCH_ERROR")
        obj = _parse_single()
        assert obj["type"] == "error"
        assert obj["error_code"] == "FETCH_ERROR"
        assert obj["message"] == "[fetch] timeout"

    def test_emit_error_without_code(self) -> None:
        jsonl_emit_error(stage="parse", detail="bad json")
        obj = _parse_single()
        assert obj["type"] == "error"
        assert obj["error_code"] == "error"
        assert obj["message"] == "[parse] bad json"

    def test_emit_progress_with_percent(self) -> None:
        jsonl_emit_progress(message="downloading", percent=42)
        obj = _parse_single()
        assert obj["type"] == "progress"
        assert obj["message"] == "downloading"
        assert obj["percent"] == 42

    def test_emit_progress_without_percent(self) -> None:
        jsonl_emit_progress(message="starting")
        obj = _parse_single()
        assert obj["type"] == "progress"
        assert obj["message"] == "starting"
        assert "percent" not in obj

    def test_emit_warning(self) -> None:
        jsonl_emit_warning(message="slow network")
        obj = _parse_single()
        assert obj["type"] == "warning"
        assert obj["message"] == "slow network"

    def test_emit_result(self) -> None:
        jsonl_emit_result(path="/tmp/out.md", success=True)
        obj = _parse_single()
        assert obj["type"] == "result"
        assert obj["data"]["path"] == "/tmp/out.md"
        assert obj["data"]["success"] is True

    def test_emit_help(self) -> None:
        cmds = [{"name": "clip", "help": "Clip a URL"}]
        jsonl_emit_help(commands=cmds)
        obj = _parse_single()
        assert obj["type"] == "result"
        assert obj["data"]["commands"] == cmds

    def test_emit_schema(self) -> None:
        jsonl_emit_schema(data={"fields": ["url"]})
        obj = _parse_single()
        assert obj["type"] == "result"

    def test_emit_dict(self) -> None:
        jsonl_emit_dict(data={"codes": ["E001"]})
        obj = _parse_single()
        assert obj["type"] == "result"


# ── Quiet mode ───────────────────────────────────────────────────


class TestQuietMode:
    """set_quiet delegates to SDK Writer quiet mode."""

    def test_quiet_suppresses_progress(self) -> None:
        set_quiet(True)
        jsonl_emit("progress", message="should be silenced")
        assert len(_read_lines()) == 0

    def test_quiet_suppresses_warning(self) -> None:
        set_quiet(True)
        jsonl_emit("warning", message="should be silenced")
        assert len(_read_lines()) == 0

    def test_quiet_preserves_result(self) -> None:
        set_quiet(True)
        jsonl_emit("result", ok=True)
        obj = _parse_single()
        assert obj["type"] == "result"

    def test_quiet_preserves_error(self) -> None:
        set_quiet(True)
        jsonl_emit("error", stage="x", detail="y", error_code="INPUT_INVALID")
        obj = _parse_single()
        assert obj["type"] == "error"

    def test_quiet_restored(self) -> None:
        set_quiet(True)
        jsonl_emit("progress", message="silenced")
        assert len(_read_lines()) == 0

        set_quiet(False)
        jsonl_emit("progress", message="visible")
        obj = _parse_single()
        assert obj["type"] == "progress"

    def test_convenience_progress_respects_quiet(self) -> None:
        set_quiet(True)
        jsonl_emit_progress(message="downloading", percent=50)
        assert len(_read_lines()) == 0

    def test_convenience_warning_respects_quiet(self) -> None:
        set_quiet(True)
        jsonl_emit_warning(message="careful")
        assert len(_read_lines()) == 0


# ── Trace ID ─────────────────────────────────────────────────────


class TestTraceId:
    """set_trace_id / get_trace_id delegate to SDK Writer."""

    def test_initially_none(self) -> None:
        assert get_trace_id() is None

    def test_set_and_get(self) -> None:
        set_trace_id("abc123")
        assert get_trace_id() == "abc123"

    def test_overwrite(self) -> None:
        set_trace_id("first")
        set_trace_id("second")
        assert get_trace_id() == "second"

    def test_empty_string_returns_none(self) -> None:
        """Empty string in Writer is normalized to None by get_trace_id."""
        set_trace_id("")
        assert get_trace_id() is None

    def test_trace_id_in_envelope(self) -> None:
        set_trace_id("my-trace-42")
        jsonl_emit("progress", message="test")
        obj = _parse_single()
        assert obj["trace_id"] == "my-trace-42"

    def test_trace_id_absent_when_none(self) -> None:
        """trace_id field absent when not set."""
        jsonl_emit("progress", message="test")
        obj = _parse_single()
        assert "trace_id" not in obj

    def test_trace_id_on_all_types(self) -> None:
        """trace_id appears on progress, result, error, warning."""
        set_trace_id("universal")
        jsonl_emit_progress(message="step")
        jsonl_emit_result(done=True)
        jsonl_emit_error(stage="x", detail="y")
        jsonl_emit_warning(message="careful")

        objs = _parse_lines()
        assert len(objs) == 4
        for obj in objs:
            assert obj["trace_id"] == "universal", f"Missing trace_id in {obj['type']}"

    def test_multiple_emits_share_trace_id(self) -> None:
        set_trace_id("consistent")
        jsonl_emit_progress(message="step1")
        jsonl_emit_progress(message="step2")
        jsonl_emit_result(final=True)

        for obj in _parse_lines():
            assert obj["trace_id"] == "consistent"


# ── Envelope structure ───────────────────────────────────────────


class TestEnvelopeStructure:
    """Verify envelope fields (version, tool, timestamp) on all types."""

    def test_version_present(self) -> None:
        jsonl_emit("progress", message="x")
        obj = _parse_single()
        assert "version" in obj

    def test_tool_present(self) -> None:
        jsonl_emit("progress", message="x")
        obj = _parse_single()
        assert obj["tool"] == "web-clip-helper"

    def test_timestamp_present(self) -> None:
        jsonl_emit("progress", message="x")
        obj = _parse_single()
        assert "timestamp" in obj
        assert obj["timestamp"].endswith("Z")

    def test_envelope_on_result(self) -> None:
        jsonl_emit_result(success=True)
        obj = _parse_single()
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj

    def test_envelope_on_error(self) -> None:
        jsonl_emit_error(stage="fetch", detail="fail", error_code="FETCH_ERROR")
        obj = _parse_single()
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj

    def test_envelope_on_warning(self) -> None:
        jsonl_emit_warning(message="caution")
        obj = _parse_single()
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj

    def test_envelope_on_progress(self) -> None:
        jsonl_emit_progress(message="working", percent=50)
        obj = _parse_single()
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
