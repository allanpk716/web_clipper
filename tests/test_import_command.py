"""Tests for the import CLI command — integration tests via CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex

runner = CliRunner()


def _run(*args: str) -> str:
    return runner.invoke(app, args).output


def _parse(output: str) -> list[dict]:
    return [json.loads(l) for l in output.strip().splitlines() if l.strip()]


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def import_dir(tmp_path: Path) -> Path:
    """Sample import directory with dynamic/, static/, and nested structures."""
    base = tmp_path / "import_source"
    base.mkdir()

    # dynamic/ with manifest
    dyn = base / "dynamic"
    dyn.mkdir()
    f1 = dyn / "2026-04-10_MyProject"
    f1.mkdir()
    (f1 / "2026-04-10_MyProject.md").write_text("# My Project\n\nContent.\n", encoding="utf-8")
    f2 = dyn / "2026-04-12_AnotherRepo"
    f2.mkdir()
    (f2 / "2026-04-12_AnotherRepo.md").write_text("# Another Repo\n", encoding="utf-8")
    (dyn / "_manifest.json").write_text(json.dumps({
        "repos": [
            {"folder": "2026-04-10_MyProject", "url": "https://github.com/u/p", "source_type": "github"},
            {"folder": "2026-04-12_AnotherRepo", "url": "https://github.com/u/a", "source_type": "github"},
        ],
    }), encoding="utf-8")

    # static/ with manifest + URL extraction
    sta = base / "static"
    sta.mkdir()
    f3 = sta / "2026-04-11_WeiboPost"
    f3.mkdir()
    (f3 / "2026-04-11_WeiboPost.md").write_text(
        "# Post\n\n**链接**: https://m.weibo.cn/status/123\n\nBody.\n", encoding="utf-8",
    )
    f4 = sta / "2026-04-13_NoURL"
    f4.mkdir()
    (f4 / "2026-04-13_NoURL.md").write_text("# No URL\n", encoding="utf-8")
    f5 = sta / "2026-04-16_WithImages"
    f5.mkdir()
    (f5 / "2026-04-16_WithImages.md").write_text("# Images\n", encoding="utf-8")
    (f5 / "images").mkdir()
    (f5 / "images" / "img_01.jpg").write_bytes(b"\xff\xd8")
    (f5 / "images" / "img_02.jpg").write_bytes(b"\xff\xd8")
    (sta / "_manifest.json").write_text(json.dumps({
        "items": [{"folder": "2026-04-11_WeiboPost", "source_type": "weibo"}],
    }), encoding="utf-8")

    # Nested non-standard subdir
    nested = base / "archive" / "2026"
    nested.mkdir(parents=True)
    f6 = nested / "2026-03-01_DeepNested"
    f6.mkdir()
    (f6 / "2026-03-01_DeepNested.md").write_text("# Deep\n", encoding="utf-8")

    return base


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    import web_clip_helper.config as cfg_mod
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    config = Config(db_path=str(tmp_path / "clips.db"), storage_path=str(tmp_path / "clips"))
    config.save(cfg_dir / "config.yaml")
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return config


# ── Dry-run ───────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_no_db_write(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir), "--dry-run")
        idx = ClipIndex(cli_config.db_path)
        assert len(idx.query_clips()) == 0
        idx.close()

    def test_dry_run_output_count(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("import", str(import_dir), "--dry-run"))
        results = [m for m in msgs if m["type"] == "result" and m.get("dry_run")]
        assert len(results) == 6  # 6 folders

    def test_dry_run_manifest_info(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("import", str(import_dir), "--dry-run"))
        proj = [m for m in msgs if "MyProject" in m.get("folder", "")]
        assert len(proj) == 1
        assert proj[0]["url"] == "https://github.com/u/p"
        assert proj[0]["manifest"] is True


# ── Actual import ─────────────────────────────────────────────────────


class TestActualImport:
    def test_import_creates_records(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("import", str(import_dir)))
        summary = [m for m in msgs if m["type"] == "result" and "imported" in m]
        assert summary[0]["imported"] == 6

        idx = ClipIndex(cli_config.db_path)
        assert len(idx.query_clips()) == 6
        idx.close()

    def test_manifest_url(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        github = [c for c in clips if c["source_type"] == "github"]
        assert len(github) == 2

    def test_url_extracted_from_markdown(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        weibo = [c for c in clips if "WeiboPost" in c.get("title", "")]
        assert len(weibo) == 1
        assert weibo[0]["url"] == "https://m.weibo.cn/status/123"

    def test_no_url_empty(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        no_url = [c for c in clips if "NoURL" in c.get("title", "")]
        assert len(no_url) == 1
        assert no_url[0]["url"] == ""

    def test_image_count(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        img = [c for c in clips if "WithImages" in c.get("title", "")]
        assert len(img) == 1
        assert img[0]["image_count"] == 2

    def test_deep_nested_found(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir))
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        deep = [c for c in clips if "DeepNested" in c.get("title", "")]
        assert len(deep) == 1


# ── Dedup ─────────────────────────────────────────────────────────────


class TestDedup:
    def test_second_import_skips_all(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir))
        msgs = _parse(_run("import", str(import_dir)))
        summary = [m for m in msgs if m["type"] == "result" and "imported" in m]
        assert summary[0]["imported"] == 0
        assert summary[0]["skipped"] == 6

    def test_partial_dedup(self, import_dir: Path, cli_config: Config) -> None:
        idx = ClipIndex(cli_config.db_path)
        idx.save_clip({
            "url": "", "title": "Test", "source_type": "web",
            "folder_path": str(import_dir / "dynamic" / "2026-04-10_MyProject"),
            "markdown_path": str(import_dir / "dynamic" / "2026-04-10_MyProject" / "2026-04-10_MyProject.md"),
        })
        idx.close()

        msgs = _parse(_run("import", str(import_dir)))
        summary = [m for m in msgs if m["type"] == "result" and "imported" in m]
        assert summary[0]["imported"] == 5
        assert summary[0]["skipped"] == 1


# ── Copy mode ─────────────────────────────────────────────────────────


class TestCopyMode:
    def test_copy_creates_files(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir), "--copy")
        storage = Path(cli_config.storage_path)
        folders = [d for d in storage.iterdir() if d.is_dir()]
        assert len(folders) == 6

    def test_copy_content_preserved(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir), "--copy")
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        proj = [c for c in clips if "MyProject" in c.get("title", "")][0]
        md = Path(proj["markdown_path"])
        assert md.exists()
        assert "Content" in md.read_text(encoding="utf-8")

    def test_copy_images(self, import_dir: Path, cli_config: Config) -> None:
        _run("import", str(import_dir), "--copy")
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        img_clip = [c for c in clips if "WithImages" in c.get("title", "")][0]
        img_dir = Path(img_clip["folder_path"]) / "images"
        assert img_dir.is_dir()
        assert len(list(img_dir.iterdir())) == 2


# ── Error / edge cases ────────────────────────────────────────────────


class TestErrors:
    def test_nonexistent_dir(self, cli_config: Config) -> None:
        msgs = _parse(_run("import", r"C:\nonexistent\xyzzy\import"))
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"

    def test_empty_dir(self, tmp_path: Path, cli_config: Config) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        msgs = _parse(_run("import", str(empty)))
        results = [m for m in msgs if m["type"] == "result" and "imported" in m]
        assert results[0]["imported"] == 0

    def test_source_type_override(self, tmp_path: Path, cli_config: Config) -> None:
        src = tmp_path / "src"
        src.mkdir()
        f = src / "2026-05-01_Article"
        f.mkdir()
        (f / "2026-05-01_Article.md").write_text("# A\n", encoding="utf-8")

        _run("import", str(src), "--source-type", "wechat")
        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert clips[0]["source_type"] == "wechat"


# ── JSONL format ──────────────────────────────────────────────────────


class TestJsonlFormat:
    def test_progress_has_envelope(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("import", str(import_dir)))
        progress = [m for m in msgs if m["type"] == "progress"]
        assert all("tool" in m for m in progress)
        assert all("version" in m for m in progress)
        assert all(m["stage"] == "import" for m in progress)

    def test_result_has_envelope(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("import", str(import_dir)))
        results = [m for m in msgs if m["type"] == "result" and "imported" in m]
        assert results[0]["tool"] == "web-clip-helper"
        assert "timestamp" in results[0]

    def test_error_has_error_code(self, cli_config: Config) -> None:
        msgs = _parse(_run("import", r"C:\nonexistent\xyzzy"))
        errors = [m for m in msgs if m["type"] == "error"]
        assert "error_code" in errors[0]

    def test_trace_id_present(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("import", str(import_dir)))
        assert all("trace_id" in m for m in msgs)
        # All messages share same trace_id
        tids = {m["trace_id"] for m in msgs}
        assert len(tids) == 1

    def test_quiet_suppresses_progress(self, import_dir: Path, cli_config: Config) -> None:
        msgs = _parse(_run("--quiet", "import", str(import_dir)))
        progress = [m for m in msgs if m["type"] == "progress"]
        assert len(progress) == 0
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) >= 1
