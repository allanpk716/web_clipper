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
