"""Tests for the error_code registry and jsonl_emit_error error_code field."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.error_codes import ErrorCode
from web_clip_helper.index import ClipIndex
from web_clip_helper.output import jsonl_emit_error

runner = CliRunner()


# ── ErrorCode registry tests ───────────────────────────────────────


class TestErrorCodeRegistry:
    """Verify the error code registry has all expected codes."""

    def test_all_codes_are_upper_snake_strings(self) -> None:
        for code in ErrorCode.all_codes():
            assert code == code.upper(), f"Code {code!r} is not UPPER_SNAKE_CASE"
            assert " " not in code, f"Code {code!r} contains spaces"

    def test_expected_codes_present(self) -> None:
        expected = [
            "INPUT_INVALID", "NOT_FOUND", "STORAGE_ERROR", "INDEX_ERROR",
            "NETWORK_ERROR", "ROUTING_ERROR", "FETCH_ERROR", "CONFIG_ERROR",
            "INTERNAL_ERROR", "REFRESH_ERROR",
        ]
        for code in expected:
            assert hasattr(ErrorCode, code), f"Missing code: {code}"
            assert getattr(ErrorCode, code) == code

    def test_describe_returns_string(self) -> None:
        for code in ErrorCode.all_codes():
            desc = ErrorCode.describe(code)
            assert isinstance(desc, str) and len(desc) > 0, f"No description for {code}"

    def test_describe_unknown_returns_fallback(self) -> None:
        assert "Unknown" in ErrorCode.describe("NONEXISTENT_CODE")

    def test_all_codes_returns_mapping(self) -> None:
        mapping = ErrorCode.all_codes()
        assert len(mapping) >= 10
        for code, desc in mapping.items():
            assert isinstance(code, str)
            assert isinstance(desc, str)


# ── jsonl_emit_error with error_code ──────────────────────────────


class TestJsonlEmitErrorCode:
    """Verify jsonl_emit_error includes/omits error_code correctly."""

    def test_with_error_code(self, capsys) -> None:
        jsonl_emit_error(stage="test", detail="msg", error_code="INPUT_INVALID")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "error"
        assert obj["error_code"] == "INPUT_INVALID"
        assert obj["stage"] == "test"
        assert obj["detail"] == "msg"

    def test_without_error_code_omits_field(self, capsys) -> None:
        jsonl_emit_error(stage="test", detail="msg")
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["type"] == "error"
        assert "error_code" not in obj

    def test_error_code_with_extra_kwargs(self, capsys) -> None:
        jsonl_emit_error(
            stage="refresh",
            detail="failed",
            clip_id=42,
            error_code="REFRESH_ERROR",
        )
        lines = capsys.readouterr().out.strip().split("\n")
        obj = json.loads(lines[0])
        assert obj["error_code"] == "REFRESH_ERROR"
        assert obj["clip_id"] == 42


# ── CLI integration: error_code in CLI error output ───────────────


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config + DB, patch get_config to use it."""
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = str(tmp_path / "clips.db")
    config = Config(db_path=db_path, storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.yaml")
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


def _run_cli(*args: str) -> str:
    return runner.invoke(app, args).output


def _parse_jsonl(output: str) -> list[dict]:
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


class TestCLIErrorCodes:
    """Verify CLI commands emit correct error_code values."""

    def test_update_no_options_emits_input_invalid(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        cid = idx.save_clip({
            "url": "https://example.com", "title": "T",
            "source_type": "web", "folder_path": "/x", "markdown_path": "/x.md",
        })
        idx.close()

        output = _run_cli("update", str(cid))
        errors = [m for m in _parse_jsonl(output) if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"

    def test_get_nonexistent_emits_not_found(self, cli_config: Path) -> None:
        output = _run_cli("get", "99999")
        errors = [m for m in _parse_jsonl(output) if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "NOT_FOUND"

    def test_update_interval_zero_emits_input_invalid(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        cid = idx.save_clip({
            "url": "https://example.com", "title": "T",
            "source_type": "web", "folder_path": "/x", "markdown_path": "/x.md",
        })
        idx.close()

        output = _run_cli("update", str(cid), "--interval", "0")
        errors = [m for m in _parse_jsonl(output) if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"

    def test_update_nonexistent_emits_not_found(self, cli_config: Path) -> None:
        output = _run_cli("update", "999", "--dynamic")
        errors = [m for m in _parse_jsonl(output) if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "NOT_FOUND"

    def test_feedback_invalid_type_emits_input_invalid(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        output = _run_cli("feedback", "Test", "--type", "invalid")
        errors = [m for m in _parse_jsonl(output) if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"


# ── Pipeline integration: error_code in pipeline error output ────


class TestPipelineErrorCodes:
    """Verify pipeline functions emit correct error_code values."""

    def test_clip_text_empty_emits_input_invalid(self, capsys) -> None:
        from web_clip_helper.config import Config
        from web_clip_helper.pipeline import clip_text

        config = Config(db_path=":memory:", storage_path="/tmp/nonexistent")
        result = clip_text("", config)
        assert result is None
        lines = capsys.readouterr().out.strip().split("\n")
        errors = [json.loads(l) for l in lines if l.strip() and json.loads(l).get("type") == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"

    def test_clip_url_routing_failure_emits_routing_error(self, capsys) -> None:
        from web_clip_helper.config import Config
        from web_clip_helper.pipeline import clip_url

        config = Config(db_path=":memory:", storage_path="/tmp/nonexistent")
        # Empty string triggers a ValueError in route_url
        result = clip_url("", config)
        assert result is None
        lines = capsys.readouterr().out.strip().split("\n")
        errors = [json.loads(l) for l in lines if l.strip() and json.loads(l).get("type") == "error"]
        assert len(errors) >= 1
        assert errors[0]["error_code"] == "ROUTING_ERROR"
