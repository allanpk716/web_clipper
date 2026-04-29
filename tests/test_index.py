"""Tests for ClipIndex SQLite CRUD operations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from web_clip_helper.index import ClipIndex


@pytest.fixture
def tmp_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


@pytest.fixture
def sample_clip() -> dict:
    """Return a minimal clip dict suitable for ``save_clip``."""
    return {
        "url": "https://example.com/article",
        "title": "Test Article",
        "source_type": "web",
        "category": "tech",
        "tags": ["python", "testing"],
        "folder_path": "/tmp/clips/2024-01-15_Test_Article",
        "markdown_path": "/tmp/clips/2024-01-15_Test_Article/2024-01-15_Test_Article.md",
        "image_count": 3,
    }


class TestClipIndexInit:
    def test_init_db_creates_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new.db"
        idx = ClipIndex(db_path)
        idx.save_clip({"source_type": "web", "folder_path": "/x", "markdown_path": "/x.md"})
        assert db_path.exists()

    def test_init_db_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "deep" / "nested" / "test.db"
        idx = ClipIndex(db_path)
        idx.save_clip({"source_type": "web", "folder_path": "/x", "markdown_path": "/x.md"})
        assert db_path.exists()

    def test_schema_has_required_fields(self, tmp_db: ClipIndex) -> None:
        conn = tmp_db._connect()
        cursor = conn.execute("PRAGMA table_info(clips)")
        columns = {row["name"] for row in cursor.fetchall()}
        expected = {
            "id", "url", "title", "source_type", "category", "tags",
            "folder_path", "markdown_path", "image_count",
            "is_dynamic", "refresh_interval_days", "last_refreshed_at",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns)

    def test_schema_has_indexes(self, tmp_db: ClipIndex) -> None:
        conn = tmp_db._connect()
        cursor = conn.execute("PRAGMA index_list(clips)")
        index_names = {row["name"] for row in cursor.fetchall()}
        assert "idx_clips_url" in index_names
        assert "idx_clips_source_type" in index_names


class TestClipIndexSave:
    def test_save_clip_returns_id(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        rid = tmp_db.save_clip(sample_clip)
        assert isinstance(rid, int)
        assert rid > 0

    def test_save_clip_auto_populates_timestamps(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        rid = tmp_db.save_clip(sample_clip)
        record = tmp_db.get_clip(rid)
        assert record is not None
        assert record["created_at"]
        assert record["updated_at"]

    def test_save_clip_preserves_explicit_timestamps(self, tmp_db: ClipIndex) -> None:
        ts = "2024-01-01T00:00:00"
        rid = tmp_db.save_clip({
            "source_type": "web",
            "folder_path": "/x",
            "markdown_path": "/x.md",
            "created_at": ts,
            "updated_at": ts,
        })
        record = tmp_db.get_clip(rid)
        assert record is not None
        assert record["created_at"] == ts

    def test_save_clip_serializes_tags(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        rid = tmp_db.save_clip(sample_clip)
        record = tmp_db.get_clip(rid)
        assert record is not None
        assert record["tags"] == ["python", "testing"]

    def test_save_clip_default_empty_tags(self, tmp_db: ClipIndex) -> None:
        rid = tmp_db.save_clip({
            "source_type": "web",
            "folder_path": "/x",
            "markdown_path": "/x.md",
        })
        record = tmp_db.get_clip(rid)
        assert record is not None
        assert record["tags"] == []

    def test_save_multiple_clips(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        id1 = tmp_db.save_clip(sample_clip)
        sample_clip["url"] = "https://example.com/other"
        id2 = tmp_db.save_clip(sample_clip)
        assert id2 > id1


class TestClipIndexGet:
    def test_get_clip_existing(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        rid = tmp_db.save_clip(sample_clip)
        record = tmp_db.get_clip(rid)
        assert record is not None
        assert record["id"] == rid
        assert record["title"] == "Test Article"

    def test_get_clip_nonexistent(self, tmp_db: ClipIndex) -> None:
        assert tmp_db.get_clip(99999) is None

    def test_get_clip_all_fields_present(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        rid = tmp_db.save_clip(sample_clip)
        record = tmp_db.get_clip(rid)
        assert record is not None
        for key in (
            "id", "url", "title", "source_type", "category", "tags",
            "folder_path", "markdown_path", "image_count",
            "is_dynamic", "refresh_interval_days", "last_refreshed_at",
            "created_at", "updated_at",
        ):
            assert key in record


class TestClipIndexQuery:
    def test_query_all(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        tmp_db.save_clip(sample_clip)
        results = tmp_db.query_clips()
        assert len(results) == 1

    def test_query_by_source_type(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        tmp_db.save_clip(sample_clip)
        sample_clip["source_type"] = "github"
        sample_clip["url"] = "https://github.com/x/y"
        tmp_db.save_clip(sample_clip)

        web_results = tmp_db.query_clips({"source_type": "web"})
        assert len(web_results) == 1
        assert web_results[0]["source_type"] == "web"

        gh_results = tmp_db.query_clips({"source_type": "github"})
        assert len(gh_results) == 1

    def test_query_by_url(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        tmp_db.save_clip(sample_clip)
        results = tmp_db.query_clips({"url": sample_clip["url"]})
        assert len(results) == 1
        assert results[0]["url"] == sample_clip["url"]

    def test_query_no_matches(self, tmp_db: ClipIndex) -> None:
        results = tmp_db.query_clips({"source_type": "nonexistent"})
        assert results == []

    def test_query_newest_first(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        sample_clip["title"] = "First"
        id1 = tmp_db.save_clip(sample_clip)
        sample_clip["url"] = "https://example.com/second"
        sample_clip["title"] = "Second"
        id2 = tmp_db.save_clip(sample_clip)
        results = tmp_db.query_clips()
        assert results[0]["id"] == id2
        assert results[1]["id"] == id1

    def test_query_combined_filters(self, tmp_db: ClipIndex, sample_clip: dict) -> None:
        tmp_db.save_clip(sample_clip)
        sample_clip["source_type"] = "github"
        sample_clip["url"] = "https://github.com/x/y"
        sample_clip["category"] = "code"
        tmp_db.save_clip(sample_clip)

        results = tmp_db.query_clips({
            "source_type": "github",
            "category": "code",
        })
        assert len(results) == 1
        assert results[0]["source_type"] == "github"


class TestClipIndexClose:
    def test_close_idempotent(self, tmp_db: ClipIndex) -> None:
        tmp_db.save_clip({"source_type": "web", "folder_path": "/x", "markdown_path": "/x.md"})
        tmp_db.close()
        tmp_db.close()  # should not raise

    def test_reconnect_after_close(self, tmp_db: ClipIndex) -> None:
        rid = tmp_db.save_clip({"source_type": "web", "folder_path": "/x", "markdown_path": "/x.md"})
        tmp_db.close()
        record = tmp_db.get_clip(rid)
        assert record is not None
        assert record["id"] == rid
