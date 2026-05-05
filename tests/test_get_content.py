"""Tests for get --content flag — returns markdown body in JSONL result."""

from __future__ import annotations

from pathlib import Path

import pytest

from web_clip_helper.index import ClipIndex


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


@pytest.fixture()
def clip_with_markdown(tmp_path: Path) -> tuple[ClipIndex, int, Path]:
    """Create a clip with a real markdown file on disk. Returns (index, clip_id, md_path)."""
    idx = ClipIndex(tmp_path / "clips.db")
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    md_path = clips_dir / "article.md"
    md_path.write_text("# Test Article\n\nSome markdown content here.\n", encoding="utf-8")

    clip_id = idx.save_clip({
        "url": "https://example.com/article",
        "title": "Test Article",
        "source_type": "web",
        "category": "tech",
        "tags": ["test"],
        "folder_path": str(clips_dir),
        "markdown_path": str(md_path),
    })
    return idx, clip_id, md_path


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config + DB, patch get_config to use it."""
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = str(tmp_path / "clips.db")
    config = cfg_mod.Config(db_path=db_path, storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.json")

    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


# ── Test: --content returns markdown body ─────────────────────────────


def test_content_flag_returns_markdown_body(
    tmp_path: Path,
    clip_with_markdown: tuple[ClipIndex, int, Path],
    monkeypatch: pytest.MonkeyPatch,
    run_sdk_cli,
) -> None:
    """When --content is set, the result includes a 'content' field with the markdown text."""
    idx, clip_id, md_path = clip_with_markdown

    monkeypatch.setattr("web_clip_helper.cli._get_index", lambda: idx)
    code, envelopes = run_sdk_cli(["get", str(clip_id), "--content"])

    assert code == 0
    result_obj = next(e for e in envelopes if e.get("type") == "result")

    assert "content" in result_obj["data"]
    assert "Some markdown content here." in result_obj["data"]["content"]


# ── Test: no --content flag omits content field ───────────────────────


def test_no_content_flag_omits_body(
    tmp_path: Path,
    clip_with_markdown: tuple[ClipIndex, int, Path],
    monkeypatch: pytest.MonkeyPatch,
    run_sdk_cli,
) -> None:
    """Without --content, no 'content' field should be present."""
    idx, clip_id, md_path = clip_with_markdown

    monkeypatch.setattr("web_clip_helper.cli._get_index", lambda: idx)
    code, envelopes = run_sdk_cli(["get", str(clip_id)])

    assert code == 0
    result_obj = next(e for e in envelopes if e.get("type") == "result")

    assert "content" not in result_obj["data"]


# ── Test: file-missing warning ────────────────────────────────────────


def test_content_flag_warns_on_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_sdk_cli,
) -> None:
    """When markdown file is missing, emit a warning and omit content field."""
    idx = ClipIndex(tmp_path / "clips.db")
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    # Save clip pointing to a non-existent file
    fake_md = clips_dir / "nonexistent.md"
    clip_id = idx.save_clip({
        "url": "https://example.com/missing",
        "title": "Missing File",
        "source_type": "web",
        "category": "",
        "tags": [],
        "folder_path": str(clips_dir),
        "markdown_path": str(fake_md),
    })

    monkeypatch.setattr("web_clip_helper.cli._get_index", lambda: idx)
    code, envelopes = run_sdk_cli(["get", str(clip_id), "--content"])

    assert code == 0
    # Should have a warning about missing file
    warnings = [e for e in envelopes if e.get("type") == "warning"]
    assert len(warnings) >= 1
    assert "not found" in warnings[0]["message"].lower() or "Markdown" in warnings[0]["message"]

    # Result should NOT include content
    result_obj = next(e for e in envelopes if e.get("type") == "result")
    assert "content" not in result_obj["data"]


# ── Test: empty markdown file returns empty string ────────────────────


def test_content_flag_empty_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_sdk_cli,
) -> None:
    """An empty markdown file returns content as empty string."""
    idx = ClipIndex(tmp_path / "clips.db")
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    md_path = clips_dir / "empty.md"
    md_path.write_text("", encoding="utf-8")

    clip_id = idx.save_clip({
        "url": "https://example.com/empty",
        "title": "Empty Article",
        "source_type": "web",
        "category": "",
        "tags": [],
        "folder_path": str(clips_dir),
        "markdown_path": str(md_path),
    })

    monkeypatch.setattr("web_clip_helper.cli._get_index", lambda: idx)
    code, envelopes = run_sdk_cli(["get", str(clip_id), "--content"])

    assert code == 0
    result_obj = next(e for e in envelopes if e.get("type") == "result")

    assert "content" in result_obj["data"]
    assert result_obj["data"]["content"] == ""


# ── Test: non-UTF8 file emits warning and omits content ───────────────


def test_content_flag_non_utf8_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_sdk_cli,
) -> None:
    """A non-UTF8 markdown file triggers a UnicodeDecodeError warning and omits content."""
    idx = ClipIndex(tmp_path / "clips.db")
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()

    md_path = clips_dir / "binary.md"
    md_path.write_bytes(b"\x80\x81\x82\xff\xfe")

    clip_id = idx.save_clip({
        "url": "https://example.com/binary",
        "title": "Binary File",
        "source_type": "web",
        "category": "",
        "tags": [],
        "folder_path": str(clips_dir),
        "markdown_path": str(md_path),
    })

    monkeypatch.setattr("web_clip_helper.cli._get_index", lambda: idx)
    code, envelopes = run_sdk_cli(["get", str(clip_id), "--content"])

    assert code == 0
    # Should have a warning about encoding
    warnings = [e for e in envelopes if e.get("type") == "warning"]
    assert len(warnings) >= 1
    assert "encoding" in warnings[0]["message"].lower() or "UnicodeDecodeError" in str(warnings[0])

    # Result should NOT include content
    result_obj = next(e for e in envelopes if e.get("type") == "result")
    assert "content" not in result_obj["data"]
