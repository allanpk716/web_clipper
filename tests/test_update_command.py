"""Tests for the update CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex

runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config + DB, patch get_config to use it.

    Returns the DB path so tests can pre-populate data.
    """
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = str(tmp_path / "clips.db")
    config = Config(db_path=db_path, storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.yaml")

    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


def _run_cli(*args: str) -> str:
    """Run the CLI and return stdout."""
    result = runner.invoke(app, args)
    return result.output


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


def _insert_clip(db_path: Path, **overrides) -> int:
    """Insert a clip into the DB and return its ID."""
    idx = ClipIndex(db_path)
    defaults = {
        "url": "https://example.com",
        "title": "Test Clip",
        "source_type": "web",
        "folder_path": "/clips/test",
        "markdown_path": "/clips/test/test.md",
    }
    defaults.update(overrides)
    cid = idx.save_clip(defaults)
    idx.close()
    return cid


# ── Tests ─────────────────────────────────────────────────────────────


class TestUpdateDynamic:
    def test_set_dynamic(self, cli_config: Path) -> None:
        """update <id> --dynamic sets is_dynamic=1."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid), "--dynamic")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["id"] == cid
        assert results[0]["is_dynamic"] == 1

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["is_dynamic"] == 1

    def test_set_no_dynamic(self, cli_config: Path) -> None:
        """update <id> --no-dynamic sets is_dynamic=0."""
        cid = _insert_clip(cli_config, is_dynamic=1)
        output = _run_cli("update", str(cid), "--no-dynamic")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["is_dynamic"] == 0

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["is_dynamic"] == 0


class TestUpdateInterval:
    def test_set_interval(self, cli_config: Path) -> None:
        """update <id> --interval 3 sets refresh_interval_days=3."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid), "--interval", "3")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["refresh_interval_days"] == 3

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["refresh_interval_days"] == 3

    def test_set_interval_minimum(self, cli_config: Path) -> None:
        """update <id> --interval 1 (minimum valid value) succeeds."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid), "--interval", "1")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["refresh_interval_days"] == 1


class TestUpdateBoth:
    def test_set_dynamic_and_interval(self, cli_config: Path) -> None:
        """update <id> --dynamic --interval 7 sets both fields."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid), "--dynamic", "--interval", "7")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["is_dynamic"] == 1
        assert results[0]["refresh_interval_days"] == 7

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["is_dynamic"] == 1
        assert clip["refresh_interval_days"] == 7


class TestUpdateErrors:
    def test_no_options(self, cli_config: Path) -> None:
        """update <id> with no options → error + exit 1."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid))
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert "at least one option" in errors[0]["detail"].lower()

    def test_nonexistent_id(self, cli_config: Path) -> None:
        """update 999 --dynamic with non-existent ID → error + exit 1."""
        output = _run_cli("update", "999", "--dynamic")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert "not found" in errors[0]["detail"]

    def test_interval_zero(self, cli_config: Path) -> None:
        """update <id> --interval 0 → error + exit 1."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid), "--interval", "0")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert "invalid interval" in errors[0]["detail"].lower()

    def test_interval_negative(self, cli_config: Path) -> None:
        """update <id> --interval -1 → error + exit 1."""
        cid = _insert_clip(cli_config)
        output = _run_cli("update", str(cid), "--interval", "-1")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert "invalid interval" in errors[0]["detail"].lower()
