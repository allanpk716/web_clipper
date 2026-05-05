"""Tests for the JSONL output layer."""

from __future__ import annotations

import pytest

from tests.conftest import _unwrap_data, _unwrap_error_message
from web_clip_helper.output import (
    jsonl_emit,
    jsonl_emit_error,
    jsonl_emit_help,
    jsonl_emit_progress,
    jsonl_emit_result,
    jsonl_emit_warning,
)


# ── Core jsonl_emit ─────────────────────────────────────────────────


class TestJsonlEmit:
    """Test jsonl_emit produces valid JSONL with type field."""

    def test_valid_json_line(self, _capture_jsonl) -> None:
        """Each emit call produces exactly one parseable JSON envelope."""
        jsonl_emit("progress", message="hello")
        envelopes = _capture_jsonl()
        assert len(envelopes) == 1

    def test_type_field_present(self, _capture_jsonl) -> None:
        jsonl_emit("progress", message="test")
        envelopes = _capture_jsonl()
        assert envelopes[0]["type"] == "progress"

    def test_kwargs_merged(self, _capture_jsonl) -> None:
        """Result kwargs are nested inside the data field."""
        jsonl_emit("result", url="https://example.com", status="ok")
        envelopes = _capture_jsonl()
        env = envelopes[0]
        assert env["type"] == "result"
        data = _unwrap_data(env)
        assert data["url"] == "https://example.com"
        assert data["status"] == "ok"

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid JSONL type"):
            jsonl_emit("bogus")

    def test_multiple_emits(self, _capture_jsonl) -> None:
        jsonl_emit("progress", message="step1")
        jsonl_emit("progress", message="step2")
        jsonl_emit("result", done=True)
        envelopes = _capture_jsonl()
        assert len(envelopes) == 3
        types = [e["type"] for e in envelopes]
        assert types == ["progress", "progress", "result"]


# ── Convenience wrappers ────────────────────────────────────────────


class TestConvenienceWrappers:
    def test_emit_error(self, _capture_jsonl) -> None:
        jsonl_emit_error(stage="fetch", detail="timeout")
        envelopes = _capture_jsonl()
        env = envelopes[0]
        assert env["type"] == "error"
        stage, detail = _unwrap_error_message(env)
        assert stage == "fetch"
        assert detail == "timeout"

    def test_emit_progress_with_percent(self, _capture_jsonl) -> None:
        jsonl_emit_progress(message="downloading", percent=42)
        envelopes = _capture_jsonl()
        obj = envelopes[0]
        assert obj["type"] == "progress"
        assert obj["message"] == "downloading"
        assert obj["percent"] == 42

    def test_emit_progress_without_percent(self, _capture_jsonl) -> None:
        jsonl_emit_progress(message="starting")
        envelopes = _capture_jsonl()
        obj = envelopes[0]
        assert "percent" not in obj
        assert obj["message"] == "starting"

    def test_emit_warning(self, _capture_jsonl) -> None:
        jsonl_emit_warning(message="slow network")
        envelopes = _capture_jsonl()
        obj = envelopes[0]
        assert obj["type"] == "warning"
        assert obj["message"] == "slow network"

    def test_emit_help(self, _capture_jsonl) -> None:
        cmds = [{"name": "clip", "help": "Clip a URL"}]
        jsonl_emit_help(commands=cmds)
        envelopes = _capture_jsonl()
        env = envelopes[0]
        assert env["type"] == "result"
        data = _unwrap_data(env)
        assert len(data["commands"]) == 1
        assert data["commands"][0]["name"] == "clip"

    def test_emit_result(self, _capture_jsonl) -> None:
        jsonl_emit_result(path="/tmp/out.md", success=True)
        envelopes = _capture_jsonl()
        env = envelopes[0]
        assert env["type"] == "result"
        data = _unwrap_data(env)
        assert data["path"] == "/tmp/out.md"


# ── Envelope fields ─────────────────────────────────────────────────


class TestJsonlEnvelope:
    """Verify version/tool/timestamp envelope fields on every message type."""

    def _parse_one(self, _capture_jsonl) -> dict:
        """Helper: capture one envelope and return it."""
        envelopes = _capture_jsonl()
        assert len(envelopes) >= 1
        return envelopes[0]

    def test_version_field_present(self, _capture_jsonl) -> None:
        """Every line includes the tool version."""
        jsonl_emit("progress", message="x")
        obj = self._parse_one(_capture_jsonl)
        assert "version" in obj
        assert isinstance(obj["version"], str)

    def test_tool_field_present(self, _capture_jsonl) -> None:
        """Every line includes the tool name."""
        jsonl_emit("progress", message="x")
        obj = self._parse_one(_capture_jsonl)
        assert obj["tool"] == "web-clip-helper"

    def test_timestamp_format(self, _capture_jsonl) -> None:
        """Timestamp is ISO 8601 UTC with millisecond precision."""
        jsonl_emit("progress", message="x")
        obj = self._parse_one(_capture_jsonl)
        ts = obj["timestamp"]
        # Verify format: YYYY-MM-DDTHH:MM:SS.ffffffZ (microsecond precision)
        assert ts.endswith("Z")
        assert len(ts) == 27  # "2026-05-05T12:34:56.213986Z"
        # Must be parseable
        from datetime import datetime

        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")

    def test_envelope_on_result(self, _capture_jsonl) -> None:
        """Result messages carry envelope fields."""
        jsonl_emit_result(success=True)
        obj = self._parse_one(_capture_jsonl)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "result"

    def test_envelope_on_error(self, _capture_jsonl) -> None:
        """Error messages carry envelope fields."""
        jsonl_emit_error(stage="fetch", detail="fail", error_code="E001")
        obj = self._parse_one(_capture_jsonl)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "error"

    def test_envelope_on_warning(self, _capture_jsonl) -> None:
        """Warning messages carry envelope fields."""
        jsonl_emit_warning(message="caution")
        obj = self._parse_one(_capture_jsonl)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "warning"

    def test_envelope_on_help(self, _capture_jsonl) -> None:
        """Help messages carry envelope fields."""
        jsonl_emit_help(commands=[{"name": "clip", "help": "Clip a URL"}])
        obj = self._parse_one(_capture_jsonl)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "result"  # help maps to result type

    def test_envelope_on_progress(self, _capture_jsonl) -> None:
        """Progress messages carry envelope fields."""
        jsonl_emit_progress(message="working", percent=50)
        obj = self._parse_one(_capture_jsonl)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "progress"

    def test_user_version_kwarg_silently_overridden(self, _capture_jsonl) -> None:
        """Passing version= as kwarg is silently replaced by envelope."""
        jsonl_emit("result", version="evil")
        obj = self._parse_one(_capture_jsonl)
        assert obj["version"] != "evil"
        assert isinstance(obj["version"], str)

    def test_user_tool_kwarg_silently_overridden(self, _capture_jsonl) -> None:
        """Passing tool= as kwarg is silently replaced by envelope."""
        jsonl_emit("result", tool="evil")
        obj = self._parse_one(_capture_jsonl)
        assert obj["tool"] == "web-clip-helper"

    def test_multiple_emits_have_independent_timestamps(self, _capture_jsonl) -> None:
        """Each emit gets its own timestamp (not cached)."""
        import time

        jsonl_emit("progress", message="first")
        time.sleep(0.01)  # small delay to ensure different timestamp
        jsonl_emit("progress", message="second")
        envelopes = _capture_jsonl()
        assert envelopes[0]["timestamp"] != envelopes[1]["timestamp"]
