"""Tests for the import command — bulk-import previously clipped data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex

runner = CliRunner()


def _run_cli(*args: str) -> str:
    return runner.invoke(app, args).output


def _parse_jsonl(output: str) -> list[dict]:
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def import_dir(tmp_path: Path) -> Path:
    """Create a sample directory structure mimicking exported clip data."""
    base = tmp_path / "import_source"
    base.mkdir()

    # --- dynamic/ with manifest ---
    dynamic = base / "dynamic"
    dynamic.mkdir()

    # Folder 1: GitHub repo (has manifest entry)
    f1 = dynamic / "2026-04-10_MyProject"
    f1.mkdir()
    (f1 / "2026-04-10_MyProject.md").write_text(
        "# My Project\n\nSome content here.\n", encoding="utf-8"
    )

    # Folder 2: Another GitHub repo
    f2 = dynamic / "2026-04-12_AnotherRepo"
    f2.mkdir()
    (f2 / "2026-04-12_AnotherRepo.md").write_text(
        "# Another Repo\n\nMore content.\n", encoding="utf-8"
    )

    # Dynamic manifest
    (dynamic / "_manifest.json").write_text(json.dumps({
        "_description": "动态内容清单",
        "repos": [
            {"folder": "2026-04-10_MyProject", "url": "https://github.com/user/myproject", "source_type": "github"},
            {"folder": "2026-04-12_AnotherRepo", "url": "https://github.com/user/another", "source_type": "github"},
        ],
    }), encoding="utf-8")

    # --- static/ with manifest ---
    static = base / "static"
    static.mkdir()

    # Folder 3: Weibo with manifest
    f3 = static / "2026-04-11_WeiboPost"
    f3.mkdir()
    (f3 / "2026-04-11_WeiboPost.md").write_text(
        "# 作者 的微博\n\n**链接**: https://m.weibo.cn/status/123456\n\nPost content.\n",
        encoding="utf-8",
    )

    # Folder 4: No manifest entry — URL should be extracted from markdown
    f4 = static / "2026-04-13_ArticleWithURL"
    f4.mkdir()
    (f4 / "2026-04-13_ArticleWithURL.md").write_text(
        "# Some Article\n\n**来源**: https://example.com/article\n\nArticle body.\n",
        encoding="utf-8",
    )

    # Folder 5: No manifest, no URL in markdown
    f5 = static / "2026-04-15_NoURL"
    f5.mkdir()
    (f5 / "2026-04-15_NoURL.md").write_text(
        "# No URL Article\n\nJust some text without a URL.\n", encoding="utf-8"
    )

    # Static manifest (only covers f3)
    (static / "_manifest.json").write_text(json.dumps({
        "_description": "静态内容清单",
        "items": [
            {"folder": "2026-04-11_WeiboPost", "source_type": "weibo"},
        ],
    }), encoding="utf-8")

    # Folder 6: with images
    f6 = static / "2026-04-16_WithImages"
    f6.mkdir()
    (f6 / "2026-04-16_WithImages.md").write_text("# With Images\n\nContent.\n", encoding="utf-8")
    img_dir = f6 / "images"
    img_dir.mkdir()
    (img_dir / "img_01.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    (img_dir / "img_02.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    return base


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Create a temporary config + DB, patch get_config."""
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config = Config(
        db_path=str(tmp_path / "clips.db"),
        storage_path=str(tmp_path / "clips"),
    )
    config.save(config_dir / "config.yaml")
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return config


# ── Dry-run tests ─────────────────────────────────────────────────────


class TestImportDryRun:
    """--dry-run should preview without writing to index."""

    def test_dry_run_finds_folders(self, import_dir: Path, cli_config: Config) -> None:
        output = _run_cli("import", str(import_dir), "--dry-run")
        messages = _parse_jsonl(output)
        progress = [m for m in messages if m["type"] == "progress"]
        results = [m for m in messages if m["type"] == "result"]
        assert len(progress) >= 1
        assert progress[0]["total_folders"] == 6
        assert progress[0]["with_manifest"] == 3  # f1, f2, f3
        assert len(results) == 6

    def test_dry_run_does_not_write_db(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir), "--dry-run")
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert len(clips) == 0

    def test_dry_run_shows_manifest_info(self, import_dir: Path, cli_config: Config) -> None:
        output = _run_cli("import", str(import_dir), "--dry-run")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        # f1 has manifest with URL
        f1_result = [r for r in results if "MyProject" in r.get("folder", "")]
        assert len(f1_result) == 1
        assert f1_result[0]["url"] == "https://github.com/user/myproject"
        assert f1_result[0]["source_type"] == "github"
        assert f1_result[0]["manifest"] is True

    def test_dry_run_shows_no_manifest(self, import_dir: Path, cli_config: Config) -> None:
        output = _run_cli("import", str(import_dir), "--dry-run")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        no_manifest = [r for r in results if r.get("manifest") is False]
        assert len(no_manifest) == 3  # f4, f5, f6


# ── Actual import tests ────────────────────────────────────────────────


class TestImportActual:
    """Real import writes to the index."""

    def test_import_creates_records(self, import_dir: Path, cli_config: Config) -> None:
        output = _run_cli("import", str(import_dir))
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert len(result) == 1
        assert result[0]["imported"] == 6
        assert result[0]["skipped"] == 0

        # Verify in DB
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert len(clips) == 6

    def test_import_with_manifest_url(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        github_clips = [c for c in clips if c["source_type"] == "github"]
        assert len(github_clips) == 2
        urls = {c["url"] for c in github_clips}
        assert "https://github.com/user/myproject" in urls
        assert "https://github.com/user/another" in urls

    def test_import_url_extracted_from_markdown(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        # f4 has "来源: https://example.com/article" in markdown
        extracted = [c for c in clips if "ArticleWithURL" in c.get("title", "")]
        assert len(extracted) == 1
        assert extracted[0]["url"] == "https://example.com/article"

    def test_import_no_url_gives_empty(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        no_url = [c for c in clips if "NoURL" in c.get("title", "")]
        assert len(no_url) == 1
        assert no_url[0]["url"] == ""

    def test_import_image_count(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        with_images = [c for c in clips if "WithImages" in c.get("title", "")]
        assert len(with_images) == 1
        assert with_images[0]["image_count"] == 2

    def test_import_title_underscore_to_space(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        titles = [c["title"] for c in clips]
        # MyProject has no underscores; AnotherRepo doesn't either
        assert "MyProject" in titles
        # WithImages has no underscores either
        assert "WithImages" in titles

    def test_import_created_at_from_folder_date(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        github_clip = [c for c in clips if c["title"] == "MyProject"][0]
        assert github_clip["created_at"].startswith("2026-04-10")

    def test_import_weibo_dynamic_flag(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        weibo = [c for c in clips if c["source_type"] == "weibo"]
        assert len(weibo) == 1
        assert weibo[0]["is_dynamic"] == 1  # weibo auto-marked dynamic


# ── Deduplication tests ────────────────────────────────────────────────


class TestImportDedup:
    """Re-importing the same data should skip existing entries."""

    def test_second_import_skips_all(self, import_dir: Path, cli_config: Config) -> None:
        # First import
        _run_cli("import", str(import_dir))

        # Second import
        output = _run_cli("import", str(import_dir))
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert result[0]["imported"] == 0
        assert result[0]["skipped"] == 6

        # DB should still have exactly 6
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert len(clips) == 6

    def test_partial_dedup(self, import_dir: Path, cli_config: Config) -> None:
        """Manually insert one clip, then import — only the new ones should be added."""
        idx = ClipIndex(cli_config.db_path)
        idx.save_clip({
            "url": "https://github.com/user/myproject",
            "title": "My Project",
            "source_type": "github",
            "folder_path": str(import_dir / "dynamic" / "2026-04-10_MyProject"),
            "markdown_path": str(import_dir / "dynamic" / "2026-04-10_MyProject" / "2026-04-10_MyProject.md"),
        })
        idx.close()

        output = _run_cli("import", str(import_dir))
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert result[0]["imported"] == 5  # 6 - 1 already existing
        assert result[0]["skipped"] == 1


# ── Error / edge case tests ────────────────────────────────────────────


class TestImportEdgeCases:
    """Edge cases and error handling."""

    def test_nonexistent_source_dir(self, cli_config: Config) -> None:
        output = _run_cli("import", "/nonexistent/path/xyz")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert "does not exist" in errors[0]["detail"]

    def test_empty_source_dir(self, tmp_path: Path, cli_config: Config) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        output = _run_cli("import", str(empty))
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["imported"] == 0
        assert results[0]["message"] == "No clip folders found in source directory"

    def test_folder_without_markdown_skipped(self, tmp_path: Path, cli_config: Config) -> None:
        """Folder matching DATE_Title pattern but no .md file → skipped."""
        src = tmp_path / "source"
        src.mkdir()
        f = src / "2026-05-01_NoMarkdown"
        f.mkdir()
        # No .md file created

        output = _run_cli("import", str(src))
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert result[0]["imported"] == 0
        assert result[0]["skipped"] == 1

    def test_folder_with_alternative_md_name(self, tmp_path: Path, cli_config: Config) -> None:
        """Folder where .md name differs from folder name — use first .md found."""
        src = tmp_path / "source"
        src.mkdir()
        f = src / "2026-05-01_AltMD"
        f.mkdir()
        (f / "readme.md").write_text("# Alt Content\n", encoding="utf-8")

        output = _run_cli("import", str(src))
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert result[0]["imported"] == 1

        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert len(clips) == 1
        assert "readme.md" in clips[0]["markdown_path"]

    def test_malformed_manifest_is_skipped(self, tmp_path: Path, cli_config: Config) -> None:
        """Malformed _manifest.json → warning, import continues."""
        src = tmp_path / "source"
        src.mkdir()

        f = src / "2026-05-01_BadManifest"
        f.mkdir()
        (f / "2026-05-01_BadManifest.md").write_text("# Content\n", encoding="utf-8")

        (src / "_manifest.json").write_text("{invalid json", encoding="utf-8")

        output = _run_cli("import", str(src))
        messages = _parse_jsonl(output)
        warnings = [m for m in messages if m["type"] == "warning"]
        result = [m for m in messages if m["type"] == "result" and "imported" in m]

        # Manifest parsing should have produced a warning
        assert len(warnings) >= 1
        assert "manifest" in warnings[0]["message"].lower()

        # But the folder should still be imported (without manifest data)
        assert result[0]["imported"] == 1

    def test_url_extraction_from_markdown_link(self, tmp_path: Path, cli_config: Config) -> None:
        """URL extracted from markdown '链接: https://...' pattern."""
        src = tmp_path / "source"
        src.mkdir()
        f = src / "2026-05-01_WithURL"
        f.mkdir()
        (f / "2026-05-01_WithURL.md").write_text(
            "# Title\n\n**链接**: https://m.weibo.cn/status/999\n\nBody.\n",
            encoding="utf-8",
        )

        output = _run_cli("import", str(src))
        messages = _parse_jsonl(output)
        _parse_jsonl(output)

        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        assert len(clips) == 1
        assert clips[0]["url"] == "https://m.weibo.cn/status/999"

    def test_url_extraction_from_source_field(self, tmp_path: Path, cli_config: Config) -> None:
        """URL extracted from 'Source: https://...' pattern."""
        src = tmp_path / "source"
        src.mkdir()
        f = src / "2026-05-01_EnglishSource"
        f.mkdir()
        (f / "2026-05-01_EnglishSource.md").write_text(
            "# English Article\n\nSource: https://example.com/en/article\n\nText.\n",
            encoding="utf-8",
        )

        output = _run_cli("import", str(src))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        assert len(clips) == 1
        assert clips[0]["url"] == "https://example.com/en/article"

    def test_non_date_folders_ignored(self, tmp_path: Path, cli_config: Config) -> None:
        """Folders not matching DATE_Title pattern are ignored."""
        src = tmp_path / "source"
        src.mkdir()
        (src / "random_folder").mkdir()
        (src / "images").mkdir()
        (src / "_internal").mkdir()
        # One valid folder
        f = src / "2026-05-01_Valid"
        f.mkdir()
        (f / "2026-05-01_Valid.md").write_text("# Valid\n", encoding="utf-8")

        output = _run_cli("import", str(src))
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert result[0]["imported"] == 1


# ─-- Copy mode tests ──────────────────────────────────────────────────


class TestImportCopy:
    """--copy mode copies files into storage_path."""

    def test_copy_creates_files_in_storage(self, import_dir: Path, cli_config: Config) -> None:
        output = _run_cli("import", str(import_dir), "--copy")
        messages = _parse_jsonl(output)
        result = [m for m in messages if m["type"] == "result" and "imported" in m]
        assert result[0]["imported"] == 6

        # Verify files exist in storage_path
        storage = Path(cli_config.storage_path)
        assert storage.is_dir()
        folders = [d for d in storage.iterdir() if d.is_dir()]
        assert len(folders) == 6

    def test_copy_preserves_content(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir), "--copy")

        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        # Read back the first clip's markdown
        for clip in clips:
            if "My Project" in clip["title"]:
                md = Path(clip["markdown_path"])
                assert md.exists()
                content = md.read_text(encoding="utf-8")
                assert "Some content here" in content
                break

    def test_copy_with_images(self, import_dir: Path, cli_config: Config) -> None:
        _run_cli("import", str(import_dir), "--copy")

        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()

        img_clip = [c for c in clips if "WithImages" in c.get("title", "")][0]
        folder = Path(img_clip["folder_path"])
        images_dir = folder / "images"
        assert images_dir.is_dir()
        assert len(list(images_dir.iterdir())) == 2
