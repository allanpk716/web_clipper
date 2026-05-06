"""Tests for empty-result handling: list, search, and tags emit count:0 result lines.

Verifies that when no items match, each command still produces at least one
type=result JSONL envelope with count=0, so agents can distinguish "success but
empty" from a process crash (R037).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex


# ── Fixtures ──────────────────────────────────────────────────────


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
    config.save(config_dir / "config.json")

    # Patch the module-level singleton
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


# ── list empty ────────────────────────────────────────────────────


class TestListEmpty:
    """list command on an empty database emits count:0 result."""

    def test_list_empty_db_has_count_zero(
        self, cli_config: Path, run_sdk_cli
    ) -> None:
        code, envelopes = run_sdk_cli(["list"])
        assert code == 0
        result_envs = [e for e in envelopes if e.get("type") == "result"]
        assert len(result_envs) == 1
        data = result_envs[0]["data"]
        assert data.get("count") == 0
        assert data.get("_total_count") == 0

    def test_quiet_list_empty_produces_result(
        self, cli_config: Path, run_sdk_cli
    ) -> None:
        code, envelopes = run_sdk_cli(["--quiet", "list"])
        assert code == 0
        result_envs = [e for e in envelopes if e.get("type") == "result"]
        assert len(result_envs) >= 1, "quiet list on empty DB must produce at least one result line"


# ── search no match ───────────────────────────────────────────────


class TestSearchNoMatch:
    """search command with no matching results emits count:0 result."""

    def test_search_no_match_has_count_zero(
        self, cli_config: Path, run_sdk_cli
    ) -> None:
        # Pre-populate with a clip so the DB is not empty, but search won't match
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/python-guide",
            "title": "Python Guide",
            "source_type": "web",
            "category": "tech",
            "tags": ["python", "guide"],
            "folder_path": "/clips/python-guide",
            "markdown_path": "/clips/python-guide/guide.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "ZZZNONEXISTENT"])
        assert code == 0
        result_envs = [e for e in envelopes if e.get("type") == "result"]
        assert len(result_envs) == 1
        data = result_envs[0]["data"]
        assert data.get("count") == 0
        assert data.get("_total_count") == 0

    def test_quiet_search_empty_produces_result(
        self, cli_config: Path, run_sdk_cli
    ) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/react-tutorial",
            "title": "React Tutorial",
            "source_type": "web",
            "category": "tech",
            "tags": ["react"],
            "folder_path": "/clips/react-tutorial",
            "markdown_path": "/clips/react-tutorial/tutorial.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["--quiet", "search", "ZZZNONEXISTENT"])
        assert code == 0
        result_envs = [e for e in envelopes if e.get("type") == "result"]
        assert len(result_envs) >= 1, "quiet search with no matches must produce at least one result line"


# ── tags empty ────────────────────────────────────────────────────


class TestTagsEmpty:
    """tags command on an empty database emits count:0 result."""

    def test_tags_empty_db_has_count_zero(
        self, cli_config: Path, run_sdk_cli
    ) -> None:
        code, envelopes = run_sdk_cli(["tags"])
        assert code == 0
        result_envs = [e for e in envelopes if e.get("type") == "result"]
        assert len(result_envs) == 1
        data = result_envs[0]["data"]
        assert data.get("count") == 0

    def test_quiet_tags_empty_produces_result(
        self, cli_config: Path, run_sdk_cli
    ) -> None:
        code, envelopes = run_sdk_cli(["--quiet", "tags"])
        assert code == 0
        result_envs = [e for e in envelopes if e.get("type") == "result"]
        assert len(result_envs) >= 1, "quiet tags on empty DB must produce at least one result line"
