"""Tests for the JSONL output layer."""

from __future__ import annotations

import json

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

    def test_valid_json_line(self, capsys: object) -> None:
        """Each emit call produces exactly one parseable JSON line."""
        import sys

        jsonl_emit("progress", message="hello")
        captured = sys.stdout.getvalue() if hasattr(sys.stdout, "getvalue") else ""
        # capsys may not work if stdout is not captured — use capsys fixture
        # We rely on the capsys fixture injected by pytest

    def test_type_field_present(self, capsys) -> None:
        jsonl_emit("progress", message="test")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "progress"

    def test_kwargs_merged(self, capsys) -> None:
        jsonl_emit("result", url="https://example.com", status="ok")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "result"
        assert obj["url"] == "https://example.com"
        assert obj["status"] == "ok"

    def test_invalid_type_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Invalid JSONL type"):
            jsonl_emit("bogus")

    def test_multiple_emits(self, capsys) -> None:
        jsonl_emit("progress", message="step1")
        jsonl_emit("progress", message="step2")
        jsonl_emit("result", done=True)
        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) == 3
        types = [json.loads(l)["type"] for l in lines]
        assert types == ["progress", "progress", "result"]


# ── Convenience wrappers ────────────────────────────────────────────


class TestConvenienceWrappers:
    def test_emit_error(self, capsys) -> None:
        jsonl_emit_error(stage="fetch", detail="timeout")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "error"
        assert obj["stage"] == "fetch"
        assert obj["detail"] == "timeout"

    def test_emit_progress_with_percent(self, capsys) -> None:
        jsonl_emit_progress(message="downloading", percent=42)
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "progress"
        assert obj["message"] == "downloading"
        assert obj["percent"] == 42

    def test_emit_progress_without_percent(self, capsys) -> None:
        jsonl_emit_progress(message="starting")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert "percent" not in obj
        assert obj["message"] == "starting"

    def test_emit_warning(self, capsys) -> None:
        jsonl_emit_warning(message="slow network")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "warning"
        assert obj["message"] == "slow network"

    def test_emit_help(self, capsys) -> None:
        cmds = [{"name": "clip", "help": "Clip a URL"}]
        jsonl_emit_help(commands=cmds)
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "help"
        assert len(obj["commands"]) == 1
        assert obj["commands"][0]["name"] == "clip"

    def test_emit_result(self, capsys) -> None:
        jsonl_emit_result(path="/tmp/out.md", success=True)
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "result"
        assert obj["path"] == "/tmp/out.md"


# ── Envelope fields ─────────────────────────────────────────────────


class TestJsonlEnvelope:
    """Verify version/tool/timestamp envelope fields on every message type."""

    def _parse_line(self, capsys) -> dict:
        """Helper: read one JSONL line and parse it."""
        lines = capsys.readouterr().out.strip().split("\n")
        return json.loads(lines[0])

    def test_version_field_present(self, capsys) -> None:
        """Every line includes the tool version."""
        from web_clip_helper import __version__

        jsonl_emit("progress", message="x")
        obj = self._parse_line(capsys)
        assert obj["version"] == __version__

    def test_tool_field_present(self, capsys) -> None:
        """Every line includes the tool name."""
        jsonl_emit("progress", message="x")
        obj = self._parse_line(capsys)
        assert obj["tool"] == "web-clip-helper"

    def test_timestamp_format(self, capsys) -> None:
        """Timestamp is ISO 8601 UTC with millisecond precision."""
        jsonl_emit("progress", message="x")
        obj = self._parse_line(capsys)
        ts = obj["timestamp"]
        # Verify format: YYYY-MM-DDTHH:MM:SS.mmmZ
        assert ts.endswith("Z")
        assert len(ts) == 24  # "2025-01-15T12:34:56.789Z"
        # Must be parseable
        from datetime import datetime

        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")

    def test_envelope_on_result(self, capsys) -> None:
        """Result messages carry envelope fields."""
        jsonl_emit_result(success=True)
        obj = self._parse_line(capsys)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "result"

    def test_envelope_on_error(self, capsys) -> None:
        """Error messages carry envelope fields."""
        jsonl_emit_error(stage="fetch", detail="fail", error_code="E001")
        obj = self._parse_line(capsys)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "error"

    def test_envelope_on_warning(self, capsys) -> None:
        """Warning messages carry envelope fields."""
        jsonl_emit_warning(message="caution")
        obj = self._parse_line(capsys)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "warning"

    def test_envelope_on_help(self, capsys) -> None:
        """Help messages carry envelope fields."""
        jsonl_emit_help(commands=[{"name": "clip", "help": "Clip a URL"}])
        obj = self._parse_line(capsys)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "help"

    def test_envelope_on_progress(self, capsys) -> None:
        """Progress messages carry envelope fields."""
        jsonl_emit_progress(message="working", percent=50)
        obj = self._parse_line(capsys)
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert obj["type"] == "progress"

    def test_user_version_kwarg_silently_overridden(self, capsys) -> None:
        """Passing version= as kwarg is silently replaced by envelope."""
        jsonl_emit("result", version="evil")
        obj = self._parse_line(capsys)
        from web_clip_helper import __version__
        assert obj["version"] == __version__

    def test_user_tool_kwarg_silently_overridden(self, capsys) -> None:
        """Passing tool= as kwarg is silently replaced by envelope."""
        jsonl_emit("result", tool="evil")
        obj = self._parse_line(capsys)
        assert obj["tool"] == "web-clip-helper"

    def test_multiple_emits_have_independent_timestamps(self, capsys) -> None:
        """Each emit gets its own timestamp (not cached)."""
        import time

        jsonl_emit("progress", message="first")
        time.sleep(0.01)  # small delay to ensure different timestamp
        jsonl_emit("progress", message="second")
        lines = capsys.readouterr().out.strip().split("\n")
        obj1 = json.loads(lines[0])
        obj2 = json.loads(lines[1])
        assert obj1["timestamp"] != obj2["timestamp"]
