"""Tests for services/import_service.py — pure business logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from web_clip_helper.services.import_service import (
    ImportCandidate,
    extract_url_from_markdown,
    build_clip_record,
    execute_import,
    scan_import_dir,
)
from web_clip_helper.index import ClipIndex


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    """Create a sample directory structure for scanning tests."""
    base = tmp_path / "source"
    base.mkdir()

    # Flat folder
    f1 = base / "2026-04-10_MyProject"
    f1.mkdir()
    (f1 / "2026-04-10_MyProject.md").write_text("# My Project\n", encoding="utf-8")

    # Nested under custom subdir (not dynamic/static)
    nested = base / "by_year" / "2026"
    nested.mkdir(parents=True)
    f2 = nested / "2026-05-01_NestedArticle"
    f2.mkdir()
    (f2 / "2026-05-01_NestedArticle.md").write_text("# Nested\n", encoding="utf-8")

    # With manifest
    (base / "_manifest.json").write_text(json.dumps({
        "items": [
            {"folder": "2026-04-10_MyProject", "url": "https://github.com/user/proj", "source_type": "github"},
        ],
    }), encoding="utf-8")

    return base


@pytest.fixture()
def candidate_no_manifest(tmp_path: Path) -> ImportCandidate:
    """A candidate without manifest data."""
    return ImportCandidate(
        folder=tmp_path / "2026-05-01_TestArticle",
        folder_name="2026-05-01_TestArticle",
        date_str="2026-05-01",
        title_raw="TestArticle",
        markdown_path=tmp_path / "2026-05-01_TestArticle" / "2026-05-01_TestArticle.md",
        manifest_entry={},
    )


# ── scan_import_dir tests ────────────────────────────────────────────


class TestScanImportDir:
    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        assert scan_import_dir(empty) == []

    def test_flat_scan(self, tmp_path: Path) -> None:
        base = tmp_path / "src"
        base.mkdir()
        f = base / "2026-01-01_Article"
        f.mkdir()
        (f / "2026-01-01_Article.md").write_text("# Test\n", encoding="utf-8")

        candidates = scan_import_dir(base)
        assert len(candidates) == 1
        assert candidates[0].folder_name == "2026-01-01_Article"

    def test_deep_nesting(self, sample_dir: Path) -> None:
        """Scan finds folders at arbitrary depth, not just dynamic/static."""
        candidates = scan_import_dir(sample_dir)
        names = [c.folder_name for c in candidates]
        assert "2026-04-10_MyProject" in names
        assert "2026-05-01_NestedArticle" in names

    def test_skips_underscore_and_images_dirs(self, tmp_path: Path) -> None:
        base = tmp_path / "src"
        base.mkdir()
        (base / "_private").mkdir()
        (base / "images").mkdir()
        f = base / "2026-01-01_Valid"
        f.mkdir()
        (f / "2026-01-01_Valid.md").write_text("# V\n", encoding="utf-8")

        candidates = scan_import_dir(base)
        assert len(candidates) == 1

    def test_no_markdown_folder_skipped(self, tmp_path: Path) -> None:
        base = tmp_path / "src"
        base.mkdir()
        f = base / "2026-01-01_NoMD"
        f.mkdir()
        # No .md file

        candidates = scan_import_dir(base)
        assert len(candidates) == 0

    def test_manifest_enrichment(self, sample_dir: Path) -> None:
        candidates = scan_import_dir(sample_dir)
        proj = [c for c in candidates if "MyProject" in c.folder_name][0]
        assert proj.url_from_manifest == "https://github.com/user/proj"
        assert proj.source_type_from_manifest == "github"


# ── extract_url_from_markdown tests ──────────────────────────────────


class TestExtractUrl:
    def test_bold_label_chinese(self) -> None:
        text = "# Title\n\n**链接**: https://example.com/a\n"
        assert extract_url_from_markdown(text) == "https://example.com/a"

    def test_plain_label(self) -> None:
        text = "来源: https://example.com/b\n"
        assert extract_url_from_markdown(text) == "https://example.com/b"

    def test_source_english(self) -> None:
        text = "Source: https://example.com/c\n"
        assert extract_url_from_markdown(text) == "https://example.com/c"

    def test_markdown_link(self) -> None:
        text = "See [the article](https://example.com/d) for details.\n"
        assert extract_url_from_markdown(text) == "https://example.com/d"

    def test_bare_url_line(self) -> None:
        text = "# Title\n\nhttps://example.com/e\n"
        assert extract_url_from_markdown(text) == "https://example.com/e"

    def test_no_url(self) -> None:
        assert extract_url_from_markdown("Just text no url") == ""

    def test_multiple_urls_returns_first_pattern(self) -> None:
        text = "**链接**: https://first.com\n\n[link](https://second.com)\n"
        assert extract_url_from_markdown(text) == "https://first.com"

    def test_url_trailing_paren_stripped(self) -> None:
        text = "**链接**: https://example.com/x)\n"
        assert extract_url_from_markdown(text) == "https://example.com/x"


# ── build_clip_record tests ──────────────────────────────────────────


class TestBuildClipRecord:
    def test_full_manifest(self, tmp_path: Path) -> None:
        md = tmp_path / "2026-01-01_Test" / "2026-01-01_Test.md"
        md.parent.mkdir()
        md.write_text("# Test\n", encoding="utf-8")

        c = ImportCandidate(
            folder=md.parent, folder_name="2026-01-01_Test",
            date_str="2026-01-01", title_raw="Test",
            markdown_path=md,
            manifest_entry={"url": "https://example.com", "source_type": "web", "category": "tech", "tags": ["python"]},
            url_from_manifest="https://example.com",
            source_type_from_manifest="web",
        )
        record = build_clip_record(c)
        assert record["url"] == "https://example.com"
        assert record["source_type"] == "web"
        assert record["category"] == "tech"
        assert record["tags"] == ["python"]
        assert record["created_at"] == "2026-01-01T00:00:00"

    def test_no_manifest_defaults(self, candidate_no_manifest: ImportCandidate) -> None:
        record = build_clip_record(candidate_no_manifest)
        assert record["url"] == ""
        assert record["source_type"] == "unknown"
        assert record["category"] == ""

    def test_source_type_override(self, candidate_no_manifest: ImportCandidate) -> None:
        record = build_clip_record(candidate_no_manifest, source_type_override="web")
        assert record["source_type"] == "web"

    def test_manifest_overrides_source_type(self, tmp_path: Path) -> None:
        md = tmp_path / "2026-01-01_T" / "2026-01-01_T.md"
        md.parent.mkdir()
        md.write_text("# T\n", encoding="utf-8")
        c = ImportCandidate(
            folder=md.parent, folder_name="2026-01-01_T",
            date_str="2026-01-01", title_raw="T",
            markdown_path=md,
            manifest_entry={"source_type": "github"},
            source_type_from_manifest="github",
        )
        record = build_clip_record(c, source_type_override="web")
        assert record["source_type"] == "github"  # manifest wins

    def test_title_underscores_to_spaces(self, candidate_no_manifest: ImportCandidate) -> None:
        candidate_no_manifest.title_raw = "My_Article_Title"
        record = build_clip_record(candidate_no_manifest)
        assert record["title"] == "My Article Title"

    def test_dynamic_weibo(self, tmp_path: Path) -> None:
        md = tmp_path / "2026-01-01_W" / "2026-01-01_W.md"
        md.parent.mkdir()
        md.write_text("# W\n", encoding="utf-8")
        c = ImportCandidate(
            folder=md.parent, folder_name="2026-01-01_W",
            date_str="2026-01-01", title_raw="W",
            markdown_path=md,
            source_type_from_manifest="weibo",
        )
        record = build_clip_record(c)
        assert record["is_dynamic"] == 1

    def test_image_count(self, tmp_path: Path) -> None:
        f = tmp_path / "2026-01-01_Img" / "2026-01-01_Img.md"
        f.parent.mkdir()
        f.write_text("# Img\n", encoding="utf-8")
        img_dir = f.parent / "images"
        img_dir.mkdir()
        (img_dir / "a.jpg").write_bytes(b"\xff")
        (img_dir / "b.png").write_bytes(b"\x89")

        c = ImportCandidate(
            folder=f.parent, folder_name="2026-01-01_Img",
            date_str="2026-01-01", title_raw="Img",
            markdown_path=f,
        )
        record = build_clip_record(c)
        assert record["image_count"] == 2


# ── execute_import tests ──────────────────────────────────────────────


class TestExecuteImport:
    def test_fresh_import(self, tmp_path: Path) -> None:
        md = tmp_path / "2026-01-01_A" / "2026-01-01_A.md"
        md.parent.mkdir()
        md.write_text("# A\n", encoding="utf-8")
        c = ImportCandidate(
            folder=md.parent, folder_name="2026-01-01_A",
            date_str="2026-01-01", title_raw="A",
            markdown_path=md,
        )

        idx = ClipIndex(tmp_path / "test.db")
        result = execute_import(idx, [c])
        idx.close()

        assert result.imported == 1
        assert result.skipped == 0
        assert result.total_scanned == 1

    def test_dedup_skips_existing(self, tmp_path: Path) -> None:
        md = tmp_path / "2026-01-01_A" / "2026-01-01_A.md"
        md.parent.mkdir()
        md.write_text("# A\n", encoding="utf-8")
        c = ImportCandidate(
            folder=md.parent, folder_name="2026-01-01_A",
            date_str="2026-01-01", title_raw="A",
            markdown_path=md,
        )

        idx = ClipIndex(tmp_path / "test.db")
        execute_import(idx, [c])  # First import
        result = execute_import(idx, [c])  # Second import
        idx.close()

        assert result.imported == 0
        assert result.skipped == 1

    def test_partial_dedup(self, tmp_path: Path) -> None:
        md_a = tmp_path / "2026-01-01_A" / "2026-01-01_A.md"
        md_a.parent.mkdir()
        md_a.write_text("# A\n", encoding="utf-8")
        md_b = tmp_path / "2026-01-02_B" / "2026-01-02_B.md"
        md_b.parent.mkdir()
        md_b.write_text("# B\n", encoding="utf-8")

        c_a = ImportCandidate(
            folder=md_a.parent, folder_name="2026-01-01_A",
            date_str="2026-01-01", title_raw="A", markdown_path=md_a,
        )
        c_b = ImportCandidate(
            folder=md_b.parent, folder_name="2026-01-02_B",
            date_str="2026-01-02", title_raw="B", markdown_path=md_b,
        )

        idx = ClipIndex(tmp_path / "test.db")
        execute_import(idx, [c_a])  # Import A
        result = execute_import(idx, [c_a, c_b])  # A dup, B new
        idx.close()

        assert result.imported == 1
        assert result.skipped == 1

    def test_imported_ids_returned(self, tmp_path: Path) -> None:
        md = tmp_path / "2026-01-01_X" / "2026-01-01_X.md"
        md.parent.mkdir()
        md.write_text("# X\n", encoding="utf-8")
        c = ImportCandidate(
            folder=md.parent, folder_name="2026-01-01_X",
            date_str="2026-01-01", title_raw="X", markdown_path=md,
        )

        idx = ClipIndex(tmp_path / "test.db")
        result = execute_import(idx, [c])
        idx.close()

        assert len(result.imported_ids) == 1
        assert isinstance(result.imported_ids[0], int)
