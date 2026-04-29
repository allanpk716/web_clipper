"""Tests for list / get / search / tags CLI commands and ClipIndex methods."""

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
def tmp_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


@pytest.fixture()
def populated_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex with several sample clips inserted."""
    idx = ClipIndex(tmp_path / "clips.db")
    idx.save_clip({
        "url": "https://example.com/python-guide",
        "title": "Python Guide",
        "source_type": "web",
        "category": "tech",
        "tags": ["python", "guide"],
        "folder_path": "/clips/python-guide",
        "markdown_path": "/clips/python-guide/guide.md",
    })
    idx.save_clip({
        "url": "https://example.com/react-tutorial",
        "title": "React Tutorial",
        "source_type": "web",
        "category": "tech",
        "tags": ["react", "javascript"],
        "folder_path": "/clips/react-tutorial",
        "markdown_path": "/clips/react-tutorial/tutorial.md",
    })
    idx.save_clip({
        "url": "https://github.com/fastapi/fastapi",
        "title": "FastAPI GitHub Repo",
        "source_type": "github",
        "category": "code",
        "tags": ["python", "fastapi", "api"],
        "folder_path": "/clips/fastapi",
        "markdown_path": "/clips/fastapi/readme.md",
    })
    return idx


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

    # Patch the module-level singleton
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


# ── ClipIndex method tests ───────────────────────────────────────────


class TestQueryByTag:
    def test_returns_matching_clips(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("python")
        assert len(results) == 2
        titles = {r["title"] for r in results}
        assert "Python Guide" in titles
        assert "FastAPI GitHub Repo" in titles

    def test_returns_empty_for_unknown_tag(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("nonexistent")
        assert results == []

    def test_tag_filter_on_empty_db(self, tmp_db: ClipIndex) -> None:
        results = tmp_db.query_clips_by_tag("anything")
        assert results == []


class TestSearchClips:
    def test_search_by_title(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("Python")
        assert len(results) == 1
        assert results[0]["title"] == "Python Guide"

    def test_search_by_url(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("fastapi")
        assert len(results) == 1
        assert "fastapi" in results[0]["url"]

    def test_search_case_insensitive(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("REACT")
        assert len(results) == 1
        assert results[0]["title"] == "React Tutorial"

    def test_search_no_match(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("nonexistent-keyword-xyz")
        assert results == []

    def test_search_empty_keyword(self, populated_db: ClipIndex) -> None:
        # Empty keyword matches everything via LIKE '%%'
        results = populated_db.search_clips("")
        assert len(results) == 3


class TestListTags:
    def test_returns_tags_with_counts(self, populated_db: ClipIndex) -> None:
        tags = populated_db.list_tags()
        tag_map = {t["tag"]: t["count"] for t in tags}
        assert tag_map["python"] == 2
        assert tag_map["guide"] == 1
        assert tag_map["react"] == 1
        assert tag_map["fastapi"] == 1

    def test_sorted_by_count_desc(self, populated_db: ClipIndex) -> None:
        tags = populated_db.list_tags()
        counts = [t["count"] for t in tags]
        assert counts == sorted(counts, reverse=True)

    def test_empty_db(self, tmp_db: ClipIndex) -> None:
        tags = tmp_db.list_tags()
        assert tags == []


class TestDeleteClip:
    def test_delete_existing(self, populated_db: ClipIndex) -> None:
        all_clips = populated_db.query_clips()
        clip_id = all_clips[0]["id"]
        assert populated_db.delete_clip(clip_id) is True
        assert populated_db.get_clip(clip_id) is None

    def test_delete_nonexistent(self, tmp_db: ClipIndex) -> None:
        assert tmp_db.delete_clip(99999) is False


# ── CLI integration tests ────────────────────────────────────────────


def _run_cli(*args: str) -> str:
    """Run the CLI and return stdout."""
    result = runner.invoke(app, args)
    return result.output


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


class TestCLIList:
    def test_list_all(self, cli_config: Path) -> None:
        # Populate the DB
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        output = _run_cli("list")
        messages = _parse_jsonl(output)
        progress = [m for m in messages if m["type"] == "progress"]
        results = [m for m in messages if m["type"] == "result"]
        assert len(progress) == 1
        assert progress[0]["count"] == 2
        assert len(results) == 2

    def test_list_by_tag(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "tags": ["python"],
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "tags": ["java"],
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        output = _run_cli("list", "--tag", "python")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["title"] == "A"

    def test_list_empty_db(self, cli_config: Path) -> None:
        output = _run_cli("list")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert results == []

    def test_list_combined_filters(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "category": "tech",
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "github", "category": "code",
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        output = _run_cli("list", "--source-type", "web", "--category", "tech")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["title"] == "A"


class TestCLIGet:
    def test_get_existing(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        cid = idx.save_clip({
            "url": "https://example.com", "title": "Test",
            "source_type": "web", "folder_path": "/x", "markdown_path": "/x.md",
        })
        idx.close()

        output = _run_cli("get", str(cid))
        messages = _parse_jsonl(output)
        assert len(messages) == 1
        assert messages[0]["type"] == "result"
        assert messages[0]["id"] == cid
        assert messages[0]["title"] == "Test"

    def test_get_nonexistent(self, cli_config: Path) -> None:
        output = _run_cli("get", "99999")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert "not found" in errors[0]["detail"]


class TestCLISearch:
    def test_search_with_results(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/python", "title": "Python Intro",
            "source_type": "web", "folder_path": "/p", "markdown_path": "/p.md",
        })
        idx.close()

        output = _run_cli("search", "python")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["title"] == "Python Intro"

    def test_search_no_results(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com", "title": "Test",
            "source_type": "web", "folder_path": "/x", "markdown_path": "/x.md",
        })
        idx.close()

        output = _run_cli("search", "nonexistent-keyword")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert results == []


class TestCLITags:
    def test_tags_with_data(self, cli_config: Path) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "tags": ["python", "web"],
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "tags": ["python"],
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        output = _run_cli("tags")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        tag_map = {r["tag"]: r["count"] for r in results}
        assert tag_map["python"] == 2
        assert tag_map["web"] == 1

    def test_tags_empty_db(self, cli_config: Path) -> None:
        output = _run_cli("tags")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert results == []
