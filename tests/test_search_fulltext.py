"""Tests for search --full fulltext search (ClipIndex + CLI)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


@pytest.fixture()
def fulltext_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex with clips that have real markdown files on disk."""
    idx = ClipIndex(tmp_path / "clips.db")
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    # Clip 1: title contains "Python", markdown mentions "asyncio"
    md1 = clips_dir / "python-guide.md"
    md1.write_text(
        "# Python Guide\n\nThis guide covers asyncio and coroutines.\n",
        encoding="utf-8",
    )
    idx.save_clip({
        "url": "https://example.com/python-guide",
        "title": "Python Guide",
        "source_type": "web",
        "category": "tech",
        "tags": ["python", "guide"],
        "folder_path": str(clips_dir),
        "markdown_path": str(md1),
    })

    # Clip 2: title has "React", markdown mentions "hooks"
    md2 = clips_dir / "react-tutorial.md"
    md2.write_text(
        "# React Tutorial\n\nLearn about React hooks and state management.\n",
        encoding="utf-8",
    )
    idx.save_clip({
        "url": "https://example.com/react-tutorial",
        "title": "React Tutorial",
        "source_type": "web",
        "category": "tech",
        "tags": ["react", "javascript"],
        "folder_path": str(clips_dir),
        "markdown_path": str(md2),
    })

    # Clip 3: title has "FastAPI", markdown has "dependency injection"
    md3 = clips_dir / "fastapi.md"
    md3.write_text(
        "# FastAPI\n\nFastAPI uses dependency injection extensively.\n",
        encoding="utf-8",
    )
    idx.save_clip({
        "url": "https://github.com/fastapi/fastapi",
        "title": "FastAPI GitHub Repo",
        "source_type": "github",
        "category": "code",
        "tags": ["python", "fastapi", "api"],
        "folder_path": str(clips_dir),
        "markdown_path": str(md3),
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
    config.save(config_dir / "config.json")

    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


# ── ClipIndex.search_clips_fulltext tests ─────────────────────────────


class TestSearchClipsFulltext:
    """Unit tests for ClipIndex.search_clips_fulltext()."""

    def test_metadata_match_only(self, fulltext_db: ClipIndex) -> None:
        """Keyword in title returns result via metadata match."""
        results = fulltext_db.search_clips_fulltext("Python")
        # "Python Guide" (title) and "FastAPI GitHub Repo" (tags python, not title)
        # Only "Python Guide" matches title
        assert len(results) == 1
        assert results[0]["title"] == "Python Guide"

    def test_content_match_only(self, fulltext_db: ClipIndex) -> None:
        """Keyword only in markdown content (not title/url) returns result."""
        results = fulltext_db.search_clips_fulltext("hooks")
        # "hooks" is only in the React tutorial's markdown
        assert len(results) == 1
        assert results[0]["title"] == "React Tutorial"

    def test_both_metadata_and_content(self, fulltext_db: ClipIndex) -> None:
        """Keyword matching both metadata and content returns de-duplicated results."""
        # "asyncio" is in the Python Guide markdown only
        results = fulltext_db.search_clips_fulltext("asyncio")
        assert len(results) == 1
        assert results[0]["title"] == "Python Guide"

    def test_metadata_matches_come_first(self, fulltext_db: ClipIndex) -> None:
        """Metadata matches (title/url) are ordered before content-only matches."""
        md_path = fulltext_db.get_clip(3)["markdown_path"]  # FastAPI
        # Rewrite FastAPI markdown to contain "React"
        Path(md_path).write_text("This framework is an alternative to React.\n", encoding="utf-8")

        results = fulltext_db.search_clips_fulltext("React")
        # "React Tutorial" matches by title, FastAPI matches by content
        assert len(results) == 2
        # Title match should come first
        assert results[0]["title"] == "React Tutorial"

    def test_no_match_at_all(self, fulltext_db: ClipIndex) -> None:
        """Keyword not in title, url, or content returns empty list."""
        results = fulltext_db.search_clips_fulltext("nonexistent-keyword-xyzzy")
        assert results == []

    def test_case_insensitive_content_match(self, fulltext_db: ClipIndex) -> None:
        """Content search is case-insensitive."""
        results = fulltext_db.search_clips_fulltext("HOOKS")
        assert len(results) == 1
        assert results[0]["title"] == "React Tutorial"

    def test_empty_keyword_returns_all(self, fulltext_db: ClipIndex) -> None:
        """Empty keyword matches all via metadata LIKE '%%'."""
        results = fulltext_db.search_clips_fulltext("")
        assert len(results) == 3

    def test_missing_markdown_file_skipped(self, tmp_path: Path) -> None:
        """Clips with non-existent markdown_path are skipped (non-fatal)."""
        idx = ClipIndex(tmp_path / "test.db")
        idx.save_clip({
            "url": "https://example.com/missing",
            "title": "Missing File Clip",
            "source_type": "web",
            "folder_path": "/nonexistent",
            "markdown_path": "/nonexistent/file.md",
        })
        # Search for keyword that's only in the (missing) markdown file
        results = idx.search_clips_fulltext("file content")
        assert results == []
        idx.close()

    def test_encoding_error_skipped(self, tmp_path: Path) -> None:
        """Clips with non-UTF-8 markdown files are skipped (non-fatal)."""
        idx = ClipIndex(tmp_path / "test.db")
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        bad_md = clips_dir / "bad.md"
        # Write bytes that are invalid UTF-8
        bad_md.write_bytes(b"\xff\xfe Invalid UTF-8 \x80\x81")
        idx.save_clip({
            "url": "https://example.com/bad",
            "title": "Bad Encoding",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(bad_md),
        })
        results = idx.search_clips_fulltext("Invalid")
        # Encoding error should be non-fatal; clip is skipped
        assert results == []
        idx.close()

    def test_empty_markdown_path_skipped(self, tmp_path: Path) -> None:
        """Clips with empty markdown_path are skipped during content scan."""
        idx = ClipIndex(tmp_path / "test.db")
        idx.save_clip({
            "url": "https://example.com/no-md",
            "title": "No Markdown",
            "source_type": "web",
            "folder_path": "/clips",
            "markdown_path": "",
        })
        results = idx.search_clips_fulltext("anything")
        assert results == []
        idx.close()

    def test_deduplication_metadata_and_content(self, fulltext_db: ClipIndex) -> None:
        """A clip matching both metadata and content is returned only once."""
        # "Python" appears in "Python Guide" title AND in its markdown content
        results = fulltext_db.search_clips_fulltext("Python")
        ids = [r["id"] for r in results]
        # Python Guide should appear exactly once
        python_guide_ids = [i for i in ids if ids.count(i) > 1]
        assert python_guide_ids == [], "No duplicates should be present"

    def test_url_match_also_considered_metadata(self, fulltext_db: ClipIndex) -> None:
        """Keyword matching url is a metadata match (comes first)."""
        results = fulltext_db.search_clips_fulltext("fastapi")
        assert len(results) >= 1
        # The FastAPI clip matches via URL
        assert any("fastapi" in r["url"] for r in results)


class TestSearchClipsFulltextEmptyDb:
    """Edge cases on empty databases."""

    def test_empty_db(self, tmp_db: ClipIndex) -> None:
        results = tmp_db.search_clips_fulltext("anything")
        assert results == []
        tmp_db.close()


# ── CLI search --full tests ───────────────────────────────────────────


class TestCLISearchFull:
    """CLI integration tests for search --full.

    Uses run_sdk_cli fixture to run commands through the SDK App and
    capture JSONL envelope output.
    """

    def test_full_flag_triggers_fulltext(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """--full flag should find results in markdown content."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        md = clips_dir / "article.md"
        md.write_text("This article discusses machine learning algorithms.\n", encoding="utf-8")

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/article",
            "title": "Article",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(md),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "--full", "machine learning"])
        progress = [e for e in envelopes if e["type"] == "progress"]
        results = [e for e in envelopes if e["type"] == "result"]

        assert len(progress) == 1
        assert len(results) == 1
        assert results[0]["data"]["title"] == "Article"

    def test_no_full_flag_metadata_only(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """Without --full, only title/URL are searched (content ignored)."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        md = clips_dir / "article.md"
        md.write_text("This article discusses machine learning algorithms.\n", encoding="utf-8")

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/article",
            "title": "Article",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(md),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "machine learning"])
        progress = [e for e in envelopes if e["type"] == "progress"]
        results = [e for e in envelopes if e["type"] == "result"]

        assert len(progress) == 1
        assert results == []

    def test_full_flag_mode_in_progress(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """--full triggers fulltext search — verified by finding content-only matches."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        md = clips_dir / "doc.md"
        md.write_text("Some content here.\n", encoding="utf-8")

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/doc",
            "title": "Document",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(md),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "--full", "Document"])
        results = [e for e in envelopes if e["type"] == "result"]
        # Full-text search finds the document by title
        assert len(results) == 1
        assert results[0]["data"]["title"] == "Document"

    def test_metadata_mode_in_progress(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """Without --full, only metadata is searched — verified by content mismatch."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/doc",
            "title": "Document",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(clips_dir / "doc.md"),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "Document"])
        # Title "Document" matches in metadata mode
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

    def test_full_search_no_results(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """--full returns empty results when no match in metadata or content."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        md = clips_dir / "doc.md"
        md.write_text("Nothing interesting here.\n", encoding="utf-8")

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/doc",
            "title": "Document",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(md),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "--full", "quantum computing"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert results == []

    def test_full_flag_case_insensitive_content(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """Content search via --full is case-insensitive."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        md = clips_dir / "case.md"
        md.write_text("Deep LEARNING frameworks are powerful.\n", encoding="utf-8")

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/case",
            "title": "Case Study",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(md),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "--full", "deep learning"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

    def test_full_search_deduplication(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
        """A clip matching both title and content appears only once."""
        clips_dir = tmp_path / "clips"
        clips_dir.mkdir()
        md = clips_dir / "python.md"
        md.write_text("Python is a great programming language.\n", encoding="utf-8")

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/python",
            "title": "Python Intro",
            "source_type": "web",
            "folder_path": str(clips_dir),
            "markdown_path": str(md),
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "--full", "Python"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
