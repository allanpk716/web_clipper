"""Tests for save_clip field defaults, migrate_field_types(), and _row_to_dict coercion."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from web_clip_helper.index import ClipIndex


@pytest.fixture
def clip_index(tmp_path):
    """Create a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


def _base_clip_data(**overrides):
    """Return minimal valid clip_data with sensible defaults."""
    data = {
        "url": "https://example.com/article",
        "title": "Test Article",
        "source_type": "generic",
        "folder_path": "/tmp/test",
        "markdown_path": "/tmp/test/article.md",
    }
    data.update(overrides)
    return data


# ── save_clip() defaults ─────────────────────────────────────────────

class TestSaveClipDefaults:
    def test_is_dynamic_default_is_zero(self, clip_index):
        """save_clip() without is_dynamic stores integer 0."""
        cid = clip_index.save_clip(_base_clip_data())
        clip = clip_index.get_clip(cid)
        assert clip["is_dynamic"] == 0
        assert isinstance(clip["is_dynamic"], int)

    def test_refresh_interval_days_default_is_seven(self, clip_index):
        """save_clip() without refresh_interval_days stores integer 7."""
        cid = clip_index.save_clip(_base_clip_data())
        clip = clip_index.get_clip(cid)
        assert clip["refresh_interval_days"] == 7
        assert isinstance(clip["refresh_interval_days"], int)

    def test_last_refreshed_at_default_is_none(self, clip_index):
        """save_clip() without last_refreshed_at stores None (SQL NULL)."""
        cid = clip_index.save_clip(_base_clip_data())
        clip = clip_index.get_clip(cid)
        assert clip["last_refreshed_at"] is None

    def test_explicit_is_dynamic_1(self, clip_index):
        """save_clip() with explicit is_dynamic=1 stores integer 1."""
        cid = clip_index.save_clip(_base_clip_data(is_dynamic=1))
        clip = clip_index.get_clip(cid)
        assert clip["is_dynamic"] == 1

    def test_explicit_refresh_interval(self, clip_index):
        """save_clip() with explicit refresh_interval_days stores it."""
        cid = clip_index.save_clip(_base_clip_data(refresh_interval_days=30))
        clip = clip_index.get_clip(cid)
        assert clip["refresh_interval_days"] == 30


# ── migrate_field_types() ────────────────────────────────────────────

class TestMigrateFieldTypes:
    def _insert_legacy_record(self, clip_index: ClipIndex, is_dynamic="", refresh_interval_days="", last_refreshed_at=""):
        """Directly insert a record with empty-string values, bypassing save_clip()."""
        # Ensure schema exists before raw SQL
        clip_index._connect()
        conn = sqlite3.connect(str(clip_index.db_path))
        conn.execute(
            "INSERT INTO clips (url, title, source_type, folder_path, markdown_path, "
            "is_dynamic, refresh_interval_days, last_refreshed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("https://legacy.com", "Legacy", "generic", "/tmp", "/tmp/a.md",
             is_dynamic, refresh_interval_days, last_refreshed_at),
        )
        conn.commit()
        conn.close()

    def test_migrates_empty_strings(self, clip_index):
        """migrate_field_types() converts empty strings to proper types."""
        self._insert_legacy_record(clip_index)
        fixed = clip_index.migrate_field_types()
        assert fixed >= 3

        clip = clip_index.query_clips()[0]
        assert clip["is_dynamic"] == 0
        assert isinstance(clip["is_dynamic"], int)
        assert clip["refresh_interval_days"] == 7
        assert isinstance(clip["refresh_interval_days"], int)
        assert clip["last_refreshed_at"] is None

    def test_idempotent(self, clip_index):
        """Running migrate_field_types() twice causes no errors."""
        self._insert_legacy_record(clip_index)
        first = clip_index.migrate_field_types()
        second = clip_index.migrate_field_types()
        assert second == 0  # Nothing to fix on second run


# ── _row_to_dict() defensive coercion ────────────────────────────────

class TestRowToDictCoercion:
    def test_is_dynamic_empty_string_coerced_to_zero(self, clip_index):
        """_row_to_dict coerces is_dynamic='' to 0."""
        conn = clip_index._connect()
        conn.execute(
            "INSERT INTO clips (url, title, source_type, folder_path, markdown_path, "
            "is_dynamic, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("https://coerce.com", "Coerce", "generic", "/tmp", "/tmp/a.md", ""),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clips WHERE url = ?", ("https://coerce.com",)).fetchone()
        d = ClipIndex._row_to_dict(row)
        assert d["is_dynamic"] == 0
        assert isinstance(d["is_dynamic"], int)

    def test_refresh_interval_days_empty_string_coerced_to_seven(self, clip_index):
        """_row_to_dict coerces refresh_interval_days='' to 7."""
        conn = clip_index._connect()
        conn.execute(
            "INSERT INTO clips (url, title, source_type, folder_path, markdown_path, "
            "refresh_interval_days, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("https://coerce2.com", "Coerce2", "generic", "/tmp", "/tmp/a.md", ""),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clips WHERE url = ?", ("https://coerce2.com",)).fetchone()
        d = ClipIndex._row_to_dict(row)
        assert d["refresh_interval_days"] == 7
        assert isinstance(d["refresh_interval_days"], int)

    def test_last_refreshed_at_empty_string_coerced_to_none(self, clip_index):
        """_row_to_dict coerces last_refreshed_at='' to None."""
        conn = clip_index._connect()
        conn.execute(
            "INSERT INTO clips (url, title, source_type, folder_path, markdown_path, "
            "last_refreshed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            ("https://coerce3.com", "Coerce3", "generic", "/tmp", "/tmp/a.md", ""),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM clips WHERE url = ?", ("https://coerce3.com",)).fetchone()
        d = ClipIndex._row_to_dict(row)
        assert d["last_refreshed_at"] is None
