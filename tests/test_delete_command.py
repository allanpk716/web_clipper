"""Tests for the delete CLI command."""

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

    Returns the tmp_path so tests can pre-populate data and create folders.
    """
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = str(tmp_path / "clips.db")
    config = Config(db_path=db_path, storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.yaml")

    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path


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


class TestDeleteExisting:
    def test_delete_existing_clip(self, cli_config: Path) -> None:
        """delete <id> removes the clip from DB and emits success result."""
        folder = cli_config / "clips" / "test"
        folder.mkdir(parents=True, exist_ok=True)
        cid = _insert_clip(
            cli_config / "clips.db",
            folder_path=str(folder),
        )
        output = _run_cli("delete", str(cid))
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["id"] == cid
        assert results[0]["folder"] == str(folder)
        assert results[0]["message"] == "Clip deleted"

        # Verify DB record is gone
        idx = ClipIndex(cli_config / "clips.db")
        assert idx.get_clip(cid) is None
        idx.close()

    def test_delete_emits_jsonl_result_with_stage(self, cli_config: Path) -> None:
        """Delete result includes stage='delete'."""
        cid = _insert_clip(cli_config / "clips.db")
        output = _run_cli("delete", str(cid))
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert results[0]["stage"] == "delete"


class TestDeleteNonexistent:
    def test_delete_nonexistent_clip(self, cli_config: Path) -> None:
        """delete 999 with non-existent ID → error with NOT_FOUND + exit 1."""
        output = _run_cli("delete", "999")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "NOT_FOUND"
        assert "not found" in errors[0]["detail"].lower()
        assert errors[0]["stage"] == "delete"


class TestDeleteFolderCleanup:
    def test_folder_removed_on_delete(self, cli_config: Path) -> None:
        """Delete removes the folder from disk when it exists."""
        folder = cli_config / "clips" / "to-delete"
        folder.mkdir(parents=True)
        (folder / "test.md").write_text("# Content", encoding="utf-8")
        assert folder.exists()

        cid = _insert_clip(
            cli_config / "clips.db",
            folder_path=str(folder),
        )
        _run_cli("delete", str(cid))

        # Folder should be gone
        assert not folder.exists()

    def test_folder_missing_is_nonfatal(self, cli_config: Path) -> None:
        """Delete succeeds even if folder_path doesn't exist on disk."""
        nonexistent = cli_config / "clips" / "nonexistent"
        cid = _insert_clip(
            cli_config / "clips.db",
            folder_path=str(nonexistent),
        )
        output = _run_cli("delete", str(cid))
        messages = _parse_jsonl(output)
        # Should have result, no error
        results = [m for m in messages if m["type"] == "result"]
        errors = [m for m in messages if m["type"] == "error"]
        assert len(results) == 1
        assert len(errors) == 0

    def test_folder_cleanup_failure_emits_warning(self, cli_config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Delete emits warning but succeeds when rmtree fails."""
        import shutil as shutil_mod

        folder = cli_config / "clips" / "protected"
        folder.mkdir(parents=True)
        (folder / "test.md").write_text("# Content", encoding="utf-8")

        cid = _insert_clip(
            cli_config / "clips.db",
            folder_path=str(folder),
        )

        # Make rmtree fail by patching on the actual module object
        original_rmtree = shutil_mod.rmtree

        def _failing_rmtree(*args, **kwargs):
            raise PermissionError("Simulated permission denied")

        monkeypatch.setattr(shutil_mod, "rmtree", _failing_rmtree)

        output = _run_cli("delete", str(cid))

        messages = _parse_jsonl(output)
        warnings = [m for m in messages if m["type"] == "warning"]
        results = [m for m in messages if m["type"] == "result"]
        assert len(warnings) == 1
        assert "Folder cleanup failed" in warnings[0]["message"]
        # Command still succeeds with result
        assert len(results) == 1

    def test_empty_folder_path_skips_cleanup(self, cli_config: Path) -> None:
        """Delete with empty folder_path skips cleanup entirely."""
        cid = _insert_clip(
            cli_config / "clips.db",
            folder_path="",
        )
        output = _run_cli("delete", str(cid))
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        warnings = [m for m in messages if m["type"] == "warning"]
        assert len(results) == 1
        assert len(warnings) == 0


class TestDeleteIsolation:
    def test_delete_does_not_affect_other_clips(self, cli_config: Path) -> None:
        """Deleting one clip leaves other clips intact."""
        cid1 = _insert_clip(cli_config / "clips.db", title="Clip A")
        cid2 = _insert_clip(cli_config / "clips.db", title="Clip B")

        _run_cli("delete", str(cid1))

        # cid1 is gone
        idx = ClipIndex(cli_config / "clips.db")
        assert idx.get_clip(cid1) is None
        # cid2 is still there
        clip2 = idx.get_clip(cid2)
        assert clip2 is not None
        assert clip2["title"] == "Clip B"
        idx.close()
