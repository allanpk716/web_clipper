"""Tests for StorageManager — directory layout, markdown saving, sanitization."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from web_clip_helper.storage import StorageManager, _sanitize_title


# ── Sanitization ────────────────────────────────────────────────────


class TestSanitizeTitle:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Hello World", "Hello World"),
            ("What's <this>?", "What's _this"),
            ('A "B:C|D/E"', "A _B_C_D_E"),
            ("Title with /slashes\\", "Title with _slashes"),
            ("   spaces   ", "spaces"),
            ("...dots...", "dots"),
            ("", "untitled"),
            ("   ...   ", "untitled"),
        ],
    )
    def test_sanitizes_unsafe_chars(self, raw, expected):
        assert _sanitize_title(raw) == expected

    def test_collapses_underscores(self):
        result = _sanitize_title("a<<<b")
        assert result == "a_b"

    def test_truncates_long_title(self):
        long_title = "A" * 300
        result = _sanitize_title(long_title)
        assert len(result) <= 200

    def test_preserves_chinese(self):
        assert _sanitize_title("中文标题") == "中文标题"


# ── StorageManager ──────────────────────────────────────────────────


class TestStorageManager:
    @pytest.fixture()
    def store(self, tmp_path: Path) -> StorageManager:
        return StorageManager(base_path=tmp_path / "clips")

    def test_create_entry_makes_directory(self, store: StorageManager):
        entry = store.create_entry("My Article", datetime(2024, 1, 15))
        assert entry.exists()
        assert entry.is_dir()
        assert "2024-01-15" in entry.name
        assert "My Article" in entry.name

    def test_create_entry_includes_images_dir(self, store: StorageManager):
        entry = store.create_entry("Test")
        images_dir = entry / "images"
        assert images_dir.exists()
        assert images_dir.is_dir()

    def test_create_entry_default_date_is_now(self, store: StorageManager):
        before = datetime.now().strftime("%Y-%m-%d")
        entry = store.create_entry("Test")
        after = datetime.now().strftime("%Y-%m-%d")
        # The date prefix should be today
        assert entry.name.startswith(before) or entry.name.startswith(after)

    def test_create_entry_sanitizes_title(self, store: StorageManager):
        entry = store.create_entry('Bad:Title/Here', datetime(2024, 6, 1))
        assert ":" not in entry.name
        assert "/" not in entry.name
        assert "2024-06-01" in entry.name

    def test_create_entry_idempotent(self, store: StorageManager):
        """Creating the same entry twice doesn't error."""
        e1 = store.create_entry("Test", datetime(2024, 1, 1))
        e2 = store.create_entry("Test", datetime(2024, 1, 1))
        assert e1 == e2

    def test_save_markdown_writes_file(self, store: StorageManager):
        entry = store.create_entry("Test Article", datetime(2024, 3, 20))
        md_path = store.save_markdown(entry, "# Hello\n\nWorld")
        assert md_path.exists()
        assert md_path.name == "2024-03-20_Test Article.md"
        content = md_path.read_text(encoding="utf-8")
        assert "# Hello" in content
        assert "World" in content

    def test_save_markdown_with_metadata(self, store: StorageManager):
        entry = store.create_entry("Meta Test", datetime(2024, 5, 10))
        md_path = store.save_markdown(
            entry,
            "Body text",
            metadata={"url": "https://example.com", "author": "Test"},
        )
        content = md_path.read_text(encoding="utf-8")
        assert "<!--" in content
        assert "url: https://example.com" in content
        assert "author: Test" in content
        assert "Body text" in content

    def test_save_markdown_without_metadata(self, store: StorageManager):
        entry = store.create_entry("No Meta", datetime(2024, 1, 1))
        md_path = store.save_markdown(entry, "Just text")
        content = md_path.read_text(encoding="utf-8")
        assert content == "Just text"
        assert "<!--" not in content

    def test_get_images_dir(self, store: StorageManager):
        entry = store.create_entry("Img Test")
        images = store.get_images_dir(entry)
        assert images == entry / "images"
        assert images.exists()

    def test_base_path_created_automatically(self, tmp_path: Path):
        """StorageManager creates its base_path on first create_entry."""
        base = tmp_path / "nonexistent" / "deep"
        store = StorageManager(base_path=base)
        entry = store.create_entry("Auto Create")
        assert base.exists()

    def test_full_layout(self, store: StorageManager):
        """Integration: create_entry + save_markdown produces correct layout."""
        dt = datetime(2024, 7, 4)
        entry = store.create_entry("Independence Day", dt)
        md = store.save_markdown(entry, "# July 4th", metadata={"source": "test"})

        # Check directory structure
        assert entry.name == "2024-07-04_Independence Day"
        assert md == entry / "2024-07-04_Independence Day.md"
        assert (entry / "images").is_dir()
