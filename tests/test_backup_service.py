"""Tests for backup_service.create_backup and helpers."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from web_clip_helper.services.backup_service import (
    BACKUP_PREFIX,
    _create_backup,
    _generate_filename,
    create_backup,
    get_backup_config_path,
    get_default_output_dir,
)


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def backup_dirs(tmp_path: Path):
    """Create a full set of backup source directories with sample files.

    Returns (config_dir, data_dir, output_dir).
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_bytes(b"key: value\n")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "clips.db").write_bytes(b"sqlite-db-content")
    clips_dir = data_dir / "clips"
    clips_dir.mkdir()
    (clips_dir / "clip1.jsonl").write_bytes(b'{"url":"https://a.com"}\n')
    (clips_dir / "clip2.jsonl").write_bytes(b'{"url":"https://b.com"}\n')
    sub = clips_dir / "sub"
    sub.mkdir()
    (sub / "nested.jsonl").write_bytes(b'{"url":"https://c.com"}\n')

    output_dir = tmp_path / "output"
    return config_dir, data_dir, output_dir


# ── BACKUP_PREFIX constant ────────────────────────────────────────


class TestBackupPrefix:
    def test_prefix_is_wch(self):
        assert BACKUP_PREFIX == "wch"


# ── get_default_output_dir / get_backup_config_path ───────────────


class TestHelperPaths:
    @patch("web_clip_helper.services.backup_service.paths")
    def test_get_default_output_dir(self, mock_paths):
        fake = Path("/fake/data")
        mock_paths.get_data_dir.return_value = fake
        assert get_default_output_dir() == fake / "backups"

    @patch("web_clip_helper.services.backup_service.paths")
    def test_get_backup_config_path(self, mock_paths):
        fake = Path("/fake/data")
        mock_paths.get_data_dir.return_value = fake
        assert get_backup_config_path() == fake / "backup-config.json"


# ── _generate_filename ────────────────────────────────────────────


class TestGenerateFilename:
    def test_basic_format(self, tmp_path: Path):
        name = _generate_filename("wch", tmp_path)
        assert name.startswith("wch-backup-")
        assert name.endswith(".zip")
        assert len(name) == len("wch-backup-20250101-120000.zip")

    def test_collision_appends_suffix(self, tmp_path: Path):
        # Create the base name so collision triggers
        existing = _generate_filename("wch", tmp_path)
        (tmp_path / existing).touch()
        name2 = _generate_filename("wch", tmp_path)
        assert name2.endswith("-2.zip")
        assert name2 != existing

    def test_multiple_collisions(self, tmp_path: Path):
        n1 = _generate_filename("wch", tmp_path)
        (tmp_path / n1).touch()
        n2 = _generate_filename("wch", tmp_path)
        (tmp_path / n2).touch()
        n3 = _generate_filename("wch", tmp_path)
        assert n3.endswith("-3.zip")

    def test_custom_prefix(self, tmp_path: Path):
        name = _generate_filename("custom", tmp_path)
        assert name.startswith("custom-backup-")


# ── Normal path ───────────────────────────────────────────────────


class TestCreateBackupNormal:
    def test_creates_valid_zip(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        zip_path = Path(result["path"])
        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "config.yaml" in names
            assert "clips.db" in names
            assert "clips/clip1.jsonl" in names
            assert "clips/clip2.jsonl" in names
            assert "clips/sub/nested.jsonl" in names

    def test_metadata_fields(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        assert "path" in result
        assert "size_bytes" in result
        assert "output_dir" in result
        assert "filename" in result
        assert result["size_bytes"] > 0
        assert result["output_dir"] == str(output_dir)
        assert result["filename"].startswith(BACKUP_PREFIX)

    def test_zip_readable(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        # Verify zip can be opened and all entries are readable
        with zipfile.ZipFile(result["path"]) as zf:
            for name in zf.namelist():
                data = zf.read(name)
                assert isinstance(data, bytes)
                assert len(data) > 0

    def test_forward_slash_paths(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            for name in zf.namelist():
                assert "\\" not in name, (
                    f"Entry {name!r} contains backslash separator"
                )


# ── Missing individual items ──────────────────────────────────────


class TestMissingItems:
    def test_missing_config_yaml(self, tmp_path: Path):
        """Zip should contain clips.db + clips/ but no config.yaml."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        clips_dir = data_dir / "clips"
        clips_dir.mkdir()
        (clips_dir / "c.jsonl").write_bytes(b"clip")

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        output_dir = tmp_path / "output"

        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            names = zf.namelist()
            assert "config.yaml" not in names
            assert "clips.db" in names
            assert "clips/c.jsonl" in names

    def test_missing_clips_db(self, tmp_path: Path):
        """Zip should contain config.yaml + clips/ but no clips.db."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        clips_dir = data_dir / "clips"
        clips_dir.mkdir()
        (clips_dir / "c.jsonl").write_bytes(b"clip")

        output_dir = tmp_path / "output"

        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            names = zf.namelist()
            assert "config.yaml" in names
            assert "clips.db" not in names
            assert "clips/c.jsonl" in names

    def test_missing_clips_directory(self, tmp_path: Path):
        """Zip should contain config.yaml + clips.db but no clips/."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")

        output_dir = tmp_path / "output"

        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            names = zf.namelist()
            assert "config.yaml" in names
            assert "clips.db" in names
            assert not any(n.startswith("clips/") for n in names)

    def test_empty_clips_directory(self, tmp_path: Path):
        """Empty clips/ dir should produce no clip entries in zip."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        (data_dir / "clips").mkdir()

        output_dir = tmp_path / "output"

        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            names = zf.namelist()
            assert "config.yaml" in names
            assert "clips.db" in names
            assert not any(n.startswith("clips/") for n in names)


# ── Output directory auto-creation ────────────────────────────────


class TestOutputDirCreation:
    def test_nonexistent_output_dir_created(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        # output_dir does NOT exist yet
        assert not output_dir.exists()
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        assert output_dir.is_dir()
        assert Path(result["path"]).parent == output_dir

    def test_existing_output_dir_works(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        output_dir.mkdir(parents=True, exist_ok=True)
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        assert Path(result["path"]).parent == output_dir


# ── Collision safety ──────────────────────────────────────────────


class TestCollisionSafety:
    def test_two_backups_get_different_names(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        r1 = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        r2 = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        # Both should exist and be different files
        assert r1["filename"] != r2["filename"]
        assert Path(r1["path"]).exists()
        assert Path(r2["path"]).exists()

    def test_collision_suffix(self, backup_dirs):
        """When two backups share the same timestamp, second gets -2 suffix."""
        config_dir, data_dir, output_dir = backup_dirs
        output_dir.mkdir(parents=True, exist_ok=True)

        # Force a fixed filename to simulate collision
        with patch(
            "web_clip_helper.services.backup_service._generate_filename",
            return_value="wch-backup-20250101-120000.zip",
        ):
            r1 = create_backup(
                config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
            )
        # Second call with same filename should get -2
        with patch(
            "web_clip_helper.services.backup_service._generate_filename",
            side_effect=lambda p, d: (
                "wch-backup-20250101-120000.zip"
                if not (d / "wch-backup-20250101-120000.zip").exists()
                else "wch-backup-20250101-120000-2.zip"
            ),
        ):
            r2 = create_backup(
                config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
            )
        assert r2["filename"].endswith("-2.zip")


# ── Error paths ───────────────────────────────────────────────────


class TestErrorPaths:
    def test_missing_data_dir_raises_oserror(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        output_dir = tmp_path / "output"

        with pytest.raises(OSError, match="Data directory does not exist"):
            create_backup(
                config_dir=config_dir,
                data_dir=tmp_path / "nonexistent_data",
                output_dir=output_dir,
            )

    def test_unwritable_output_dir_raises(self, tmp_path: Path):
        """output_dir inside a file path should fail."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create a file where output_dir should be — mkdir will fail
        blocker = tmp_path / "blocker_file"
        blocker.write_text("blocking")

        with pytest.raises((OSError, FileExistsError)):
            create_backup(
                config_dir=config_dir,
                data_dir=data_dir,
                output_dir=blocker / "nested",
            )

    @patch("web_clip_helper.services.backup_service.paths")
    def test_none_paths_use_defaults(self, mock_paths):
        """When all paths are None, defaults are fetched from paths module."""
        fake_data = Path("/nonexistent/fake/data")
        fake_config = Path("/nonexistent/fake/config")
        mock_paths.get_data_dir.return_value = fake_data
        mock_paths.get_config_dir.return_value = fake_config

        with pytest.raises(OSError, match="Data directory does not exist"):
            create_backup(config_dir=None, data_dir=None, output_dir=None)


# ── Atomic write / cleanup ───────────────────────────────────────


class TestAtomicWrite:
    def test_no_tmp_file_left_on_success(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        # No .tmp files should remain
        tmp_files = list(output_dir.glob("*.tmp"))
        assert len(tmp_files) == 0
        # The real zip exists
        assert Path(result["path"]).exists()

    def test_tmp_cleaned_on_error(self, tmp_path: Path):
        """If zip creation fails mid-way, .tmp file should be cleaned up."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        clips_dir = data_dir / "clips"
        clips_dir.mkdir()
        (clips_dir / "c.jsonl").write_bytes(b"clip")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Patch zipfile.ZipFile.__enter__ to raise, simulating failure
        with patch("zipfile.ZipFile.__enter__", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                create_backup(
                    config_dir=config_dir,
                    data_dir=data_dir,
                    output_dir=output_dir,
                )

        tmp_files = list(output_dir.glob("*.tmp"))
        assert len(tmp_files) == 0


# ── Zip content integrity ─────────────────────────────────────────


class TestZipContentIntegrity:
    def test_config_yaml_content_preserved(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        original = (config_dir / "config.yaml").read_bytes()
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            assert zf.read("config.yaml") == original

    def test_clips_db_content_preserved(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        original = (data_dir / "clips.db").read_bytes()
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            assert zf.read("clips.db") == original

    def test_clips_file_content_preserved(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        clip_path = data_dir / "clips" / "clip1.jsonl"
        original = clip_path.read_bytes()
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            assert zf.read("clips/clip1.jsonl") == original

    def test_nested_clips_content_preserved(self, backup_dirs):
        config_dir, data_dir, output_dir = backup_dirs
        nested = data_dir / "clips" / "sub" / "nested.jsonl"
        original = nested.read_bytes()
        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        with zipfile.ZipFile(result["path"]) as zf:
            assert zf.read("clips/sub/nested.jsonl") == original


# ── Boundary conditions ───────────────────────────────────────────


class TestBoundaryConditions:
    def test_all_items_missing_but_data_dir_exists(self, tmp_path: Path):
        """data_dir exists but has no clips.db, no clips/, no config.yaml."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        data_dir = tmp_path / "data"
        data_dir.mkdir()

        output_dir = tmp_path / "output"

        result = create_backup(
            config_dir=config_dir, data_dir=data_dir, output_dir=output_dir,
        )
        # Should succeed with an empty zip (or zip with no entries)
        assert Path(result["path"]).exists()
        assert result["size_bytes"] > 0  # zip overhead even with no entries

        with zipfile.ZipFile(result["path"]) as zf:
            names = zf.namelist()
            assert len(names) == 0
