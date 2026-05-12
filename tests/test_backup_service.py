"""Tests for backup_service — create, list, cleanup, config show/config set."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import agentsdk.backup
import pytest

from web_clip_helper.services.backup_service import (
    BACKUP_PREFIX,
    _create_backup,
    _generate_filename,
    cleanup_backups,
    create_backup,
    get_backup_config_path,
    get_default_output_dir,
    list_backups,
    set_backup_config,
    show_backup_config,
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


# ── list_backups ──────────────────────────────────────────────────


class TestListBackups:
    def test_empty_dir_returns_empty_list(self, tmp_path: Path):
        result = list_backups(output_dir=str(tmp_path))
        assert result == []

    def test_nonexistent_dir_returns_empty_list(self, tmp_path: Path):
        result = list_backups(output_dir=str(tmp_path / "nope"))
        assert result == []

    def test_lists_backups(self, tmp_path: Path):
        """Create real backups and verify list_backups finds them."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        output_dir = tmp_path / "output"

        create_backup(config_dir=config_dir, data_dir=data_dir, output_dir=output_dir)

        result = list_backups(output_dir=str(output_dir))
        assert len(result) == 1
        entry = result[0]
        assert "filename" in entry
        assert "size_bytes" in entry
        assert "created_at" in entry
        assert entry["size_bytes"] > 0

    def test_returns_multiple_backups(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        output_dir = tmp_path / "output"

        create_backup(config_dir=config_dir, data_dir=data_dir, output_dir=output_dir)
        create_backup(config_dir=config_dir, data_dir=data_dir, output_dir=output_dir)

        result = list_backups(output_dir=str(output_dir))
        assert len(result) == 2

    def test_default_output_dir(self):
        """When output_dir is None, uses get_default_output_dir."""
        with patch(
            "web_clip_helper.services.backup_service.get_default_output_dir",
            return_value=Path("/fake/backups"),
        ):
            with patch("agentsdk.backup.ListBackups", return_value=[]):
                list_backups(output_dir=None)

    def test_created_at_is_iso_string(self, tmp_path: Path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        output_dir = tmp_path / "output"

        create_backup(config_dir=config_dir, data_dir=data_dir, output_dir=output_dir)

        result = list_backups(output_dir=str(output_dir))
        assert len(result) == 1
        # created_at should be a string (ISO format) or None
        assert isinstance(result[0]["created_at"], (str, type(None)))


# ── show_backup_config ────────────────────────────────────────────


class TestShowBackupConfig:
    def test_defaults_when_no_config_file(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        result = show_backup_config(config_path=str(config_path))
        assert result["source"] == "defaults"
        assert result["retention_policy"]["daily"] == 7
        assert result["retention_policy"]["weekly"] == 4
        assert result["retention_policy"]["monthly"] == 6
        assert "output_dir" in result

    def test_reads_existing_config(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "retention_policy": {"daily": 3, "weekly": 2, "monthly": 1},
                    "output_dir": "/custom/backups",
                }
            )
        )
        result = show_backup_config(config_path=str(config_path))
        assert result["source"] == "file"
        assert result["retention_policy"]["daily"] == 3
        assert result["retention_policy"]["weekly"] == 2
        assert result["retention_policy"]["monthly"] == 1
        assert result["output_dir"] == "/custom/backups"

    def test_default_config_path_used_when_none(self):
        with patch(
            "web_clip_helper.services.backup_service.get_backup_config_path",
            return_value=Path("/fake/backup-config.json"),
        ):
            with patch("agentsdk.backup.LoadBackupConfig") as mock_load:
                show_backup_config(config_path=None)
                mock_load.assert_called_once()
                # Verify the path string was passed (platform-normalized)
                call_arg = mock_load.call_args[0][0]
                assert "backup-config.json" in call_arg


# ── set_backup_config ─────────────────────────────────────────────


class TestSetBackupConfig:
    def test_set_daily(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        result = set_backup_config("retention_policy.daily", "5", config_path=str(config_path))
        assert result["retention_policy"]["daily"] == 5
        assert result["source"] == "file"

        # Verify persisted
        loaded = json.loads(config_path.read_text())
        assert loaded["retention_policy"]["daily"] == 5

    def test_set_weekly(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        result = set_backup_config("retention_policy.weekly", "10", config_path=str(config_path))
        assert result["retention_policy"]["weekly"] == 10

    def test_set_monthly(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        result = set_backup_config("retention_policy.monthly", "12", config_path=str(config_path))
        assert result["retention_policy"]["monthly"] == 12

    def test_set_output_dir(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        result = set_backup_config("output_dir", "/new/path", config_path=str(config_path))
        assert result["output_dir"] == "/new/path"

    def test_update_preserves_other_values(self, tmp_path: Path):
        """Setting daily should not change weekly/monthly."""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "retention_policy": {"daily": 7, "weekly": 4, "monthly": 6},
                    "output_dir": "",
                }
            )
        )
        set_backup_config("retention_policy.daily", "3", config_path=str(config_path))
        result = show_backup_config(config_path=str(config_path))
        assert result["retention_policy"]["daily"] == 3
        assert result["retention_policy"]["weekly"] == 4
        assert result["retention_policy"]["monthly"] == 6

    def test_unknown_key_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        with pytest.raises(ValueError, match="Unknown config key"):
            set_backup_config("bogus_key", "1", config_path=str(config_path))

    def test_retention_zero_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        with pytest.raises(ValueError, match="positive integer"):
            set_backup_config("retention_policy.daily", "0", config_path=str(config_path))

    def test_retention_negative_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        with pytest.raises(ValueError, match="positive integer"):
            set_backup_config("retention_policy.weekly", "-1", config_path=str(config_path))

    def test_retention_non_integer_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        with pytest.raises(ValueError, match="positive integer"):
            set_backup_config("retention_policy.monthly", "abc", config_path=str(config_path))

    def test_output_dir_empty_raises(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        with pytest.raises(ValueError, match="non-empty string"):
            set_backup_config("output_dir", "", config_path=str(config_path))

    def test_string_coercion_for_int(self, tmp_path: Path):
        """Value comes as string from CLI — ensure int coercion works."""
        config_path = tmp_path / "config.json"
        result = set_backup_config("retention_policy.daily", " 14 ", config_path=str(config_path))
        assert result["retention_policy"]["daily"] == 14

    def test_default_config_path_used_when_none(self):
        with patch(
            "web_clip_helper.services.backup_service.get_backup_config_path",
            return_value=Path("/fake/backup-config.json"),
        ):
            with patch("agentsdk.backup.LoadBackupConfig") as mock_load, \
                 patch("agentsdk.backup.SaveBackupConfig") as mock_save:
                set_backup_config("retention_policy.daily", "5", config_path=None)
                mock_load.assert_called_once()
                mock_save.assert_called_once()


# ── cleanup_backups ───────────────────────────────────────────────


class TestCleanupBackups:
    def test_empty_dir(self, tmp_path: Path):
        config_path = tmp_path / "config.json"
        result = cleanup_backups(
            output_dir=str(tmp_path / "no_backups"),
            config_path=str(config_path),
        )
        assert result["kept"] == []
        assert result["removed"] == []
        assert result["total_before"] == 0

    def test_cleanup_removes_old(self, tmp_path: Path):
        """Verify cleanup calls GFSRotate and returns correct structure."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        output_dir = tmp_path / "output"

        for _ in range(5):
            create_backup(config_dir=config_dir, data_dir=data_dir, output_dir=output_dir)

        config_path = tmp_path / "config.json"
        set_backup_config("retention_policy.daily", "1", config_path=str(config_path))

        # Mock GFSRotate to simulate rotation that keeps 1, removes 4
        fake_rotation = agentsdk.backup.RotationResult(
            kept=["newest.zip"], removed=["old1.zip", "old2.zip", "old3.zip", "old4.zip"],
        )
        with patch("agentsdk.backup.GFSRotate", return_value=fake_rotation):
            result = cleanup_backups(
                output_dir=str(output_dir),
                config_path=str(config_path),
            )

        assert result["total_before"] == 5
        assert len(result["kept"]) == 1
        assert len(result["removed"]) == 4

    def test_cleanup_keeps_files_on_disk(self, tmp_path: Path):
        """After cleanup, 'kept' files should exist and 'removed' files should not."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("k: v\n")
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "clips.db").write_bytes(b"db")
        output_dir = tmp_path / "output"

        for _ in range(3):
            create_backup(config_dir=config_dir, data_dir=data_dir, output_dir=output_dir)

        config_path = tmp_path / "config.json"
        set_backup_config("retention_policy.daily", "1", config_path=str(config_path))

        result = cleanup_backups(
            output_dir=str(output_dir),
            config_path=str(config_path),
        )

        for fname in result["kept"]:
            assert (output_dir / fname).exists(), f"kept file {fname} missing"
        for fname in result["removed"]:
            assert not (output_dir / fname).exists(), f"removed file {fname} still on disk"

    def test_default_paths_used_when_none(self):
        with patch(
            "web_clip_helper.services.backup_service.get_default_output_dir",
            return_value=Path("/fake/output"),
        ), patch(
            "web_clip_helper.services.backup_service.get_backup_config_path",
            return_value=Path("/fake/config.json"),
        ), patch("agentsdk.backup.LoadBackupConfig"), \
           patch("agentsdk.backup.ListBackups", return_value=[]):
            # With empty list, cleanup returns early without calling GFSRotate
            result = cleanup_backups(output_dir=None, config_path=None)
            assert result["total_before"] == 0
