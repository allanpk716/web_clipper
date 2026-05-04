"""Tests for the error_code registry and jsonl_emit_error error_code field."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.error_codes import ErrorCode, EXIT_CODE_MAP, exit_code_for
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
            "INTERNAL_ERROR", "REFRESH_ERROR", "TIMEOUT_ERROR", "RESOURCE_LOCKED",
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


# ── EXIT_CODE_MAP and exit_code_for tests ────────────────────────


class TestExitCodeMap:
    """Verify EXIT_CODE_MAP covers all standard error codes with values 1-5."""

    def test_all_standard_codes_mapped(self) -> None:
        """Every ErrorCode constant should have an entry in EXIT_CODE_MAP."""
        for code in ErrorCode.all_codes():
            assert code in EXIT_CODE_MAP, f"EXIT_CODE_MAP missing: {code}"

    def test_exit_codes_in_range(self) -> None:
        """All exit codes should be in 1-5."""
        for code, value in EXIT_CODE_MAP.items():
            assert 1 <= value <= 5, f"{code} maps to {value}, expected 1-5"

    def test_semantic_grouping(self) -> None:
        """Verify the semantic exit code grouping per spec."""
        # Exit 1 — fatal / unknown
        assert EXIT_CODE_MAP["INTERNAL_ERROR"] == 1
        assert EXIT_CODE_MAP["FATAL_CRASH"] == 1
        # Exit 2 — input / config
        assert EXIT_CODE_MAP["INPUT_INVALID"] == 2
        assert EXIT_CODE_MAP["CONFIG_ERROR"] == 2
        # Exit 3 — resource / dependency
        assert EXIT_CODE_MAP["NOT_FOUND"] == 3
        assert EXIT_CODE_MAP["STORAGE_ERROR"] == 3
        assert EXIT_CODE_MAP["INDEX_ERROR"] == 3
        assert EXIT_CODE_MAP["REFRESH_ERROR"] == 3
        # Exit 4 — network / third-party
        assert EXIT_CODE_MAP["NETWORK_ERROR"] == 4
        assert EXIT_CODE_MAP["FETCH_ERROR"] == 4
        assert EXIT_CODE_MAP["ROUTING_ERROR"] == 4
        assert EXIT_CODE_MAP["TIMEOUT_ERROR"] == 4
        # Exit 5 — concurrency
        assert EXIT_CODE_MAP["RESOURCE_LOCKED"] == 5


class TestExitCodeFor:
    """Verify exit_code_for() function behavior."""

    def test_known_codes_return_mapped_value(self) -> None:
        assert exit_code_for("INTERNAL_ERROR") == 1
        assert exit_code_for("FATAL_CRASH") == 1
        assert exit_code_for("INPUT_INVALID") == 2
        assert exit_code_for("CONFIG_ERROR") == 2
        assert exit_code_for("NOT_FOUND") == 3
        assert exit_code_for("STORAGE_ERROR") == 3
        assert exit_code_for("NETWORK_ERROR") == 4
        assert exit_code_for("FETCH_ERROR") == 4
        assert exit_code_for("RESOURCE_LOCKED") == 5

    def test_unknown_code_returns_default_1(self) -> None:
        """Unknown error codes should fall back to exit 1 (fatal / unknown)."""
        assert exit_code_for("SOME_NEW_ERROR") == 1
        assert exit_code_for("") == 1

    def test_non_standard_but_recognized_codes(self) -> None:
        """Non-standard codes used in CLI should also map correctly."""
        assert exit_code_for("INVALID_TYPE") == 2
        assert exit_code_for("NO_CUSTOM_PROMPT") == 2
        assert exit_code_for("URL_ROUTE_ERROR") == 4


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
