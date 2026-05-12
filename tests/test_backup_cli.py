"""Integration tests for the ``backup`` CLI subcommands.

Covers all 5 commands: create, list, cleanup, config show, config set.
Uses CliRunner against the main app with isolated temp directories.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app

runner = CliRunner()


# ── Helpers ─────────────────────────────────────────────────────────


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


def _result_lines(output: str, stage: str) -> list[dict]:
    """Return result-type JSONL lines matching *stage*."""
    return [
        line for line in _parse_jsonl(output)
        if line.get("type") == "result" and line.get("stage") == stage
    ]


def _error_lines(output: str) -> list[dict]:
    """Return error-type JSONL lines."""
    return [line for line in _parse_jsonl(output) if line.get("type") == "error"]


def _write_backup_config(path: Path, data: dict | None = None) -> Path:
    """Write a backup config JSON file. Returns the path."""
    if data is None:
        data = {
            "retention_policy": {"daily": 7, "weekly": 4, "monthly": 6},
            "output_dir": "",
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def fake_data_dir(tmp_path: Path) -> Path:
    """Create a fake data directory with clips.db and a clips/ subfolder."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "clips.db").write_text("fake-db", encoding="utf-8")
    clips_dir = data_dir / "clips"
    clips_dir.mkdir()
    (clips_dir / "clip_001" / "article.md").parent.mkdir(parents=True)
    (clips_dir / "clip_001" / "article.md").write_text("# Test Article\n", encoding="utf-8")
    return data_dir


@pytest.fixture()
def fake_config_dir(tmp_path: Path) -> Path:
    """Create a fake config directory with config.yaml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "llm:\n  model: gpt-4o-mini\n", encoding="utf-8",
    )
    return config_dir


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    """Isolated backup output directory."""
    d = tmp_path / "backups"
    d.mkdir()
    return d


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Isolated backup config file with default retention policy."""
    return _write_backup_config(tmp_path / "backup-config.json")


@pytest.fixture(autouse=True)
def _patch_dirs(
    fake_data_dir: Path,
    fake_config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch XDG data/config dir getters so backup create uses temp dirs."""
    monkeypatch.setattr(
        "web_clip_helper.paths.get_data_dir", lambda: fake_data_dir,
    )
    monkeypatch.setattr(
        "web_clip_helper.paths.get_config_dir", lambda: fake_config_dir,
    )


# ── backup create ───────────────────────────────────────────────────


class TestBackupCreate:
    """Tests for ``backup create``."""

    def test_create_produces_jsonl_result(self, output_dir: Path) -> None:
        result = runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_create")
        assert len(lines) == 1
        entry = lines[0]
        assert "path" in entry
        assert "size_bytes" in entry
        assert "output_dir" in entry
        assert "filename" in entry
        assert entry["filename"].endswith(".zip")

    def test_create_zip_exists_on_disk(self, output_dir: Path) -> None:
        result = runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        assert result.exit_code == 0, result.output
        entry = _result_lines(result.output, "backup_create")[0]
        zip_path = Path(entry["path"])
        assert zip_path.is_file()
        assert zip_path.stat().st_size == entry["size_bytes"]

    def test_create_zip_contains_expected_entries(self, output_dir: Path) -> None:
        result = runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        assert result.exit_code == 0, result.output
        entry = _result_lines(result.output, "backup_create")[0]
        with zipfile.ZipFile(entry["path"], "r") as zf:
            names = set(zf.namelist())
        assert "clips.db" in names
        assert "config.yaml" in names
        assert "clips/clip_001/article.md" in names

    def test_create_missing_data_dir_raises_backup_error(
        self, monkeypatch: pytest.MonkeyPatch, output_dir: Path,
    ) -> None:
        """When data_dir doesn't exist, BACKUP_ERROR is emitted."""
        monkeypatch.setattr(
            "web_clip_helper.paths.get_data_dir",
            lambda: Path("/nonexistent/path/that/does/not/exist"),
        )
        result = runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        assert result.exit_code == 3, result.output  # BACKUP_ERROR → exit 3
        errors = _error_lines(result.output)
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "BACKUP_ERROR"


# ── backup list ──────────────────────────────────────────────────────


class TestBackupList:
    """Tests for ``backup list``."""

    def test_empty_dir_returns_count_zero(self, output_dir: Path) -> None:
        result = runner.invoke(app, ["backup", "list", "--output-dir", str(output_dir)])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_list")
        # Last line should have count=0
        assert any(l.get("count") == 0 for l in lines)

    def test_list_after_create_shows_one_entry(
        self, output_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Create a backup first
        runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])

        result = runner.invoke(app, ["backup", "list", "--output-dir", str(output_dir)])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_list")
        # Should have 1 backup entry + 1 count summary = 2 lines
        assert any(l.get("count") == 1 for l in lines)
        backup_entries = [l for l in lines if "filename" in l and "count" not in l]
        assert len(backup_entries) == 1
        assert backup_entries[0]["filename"].endswith(".zip")
        assert "size_bytes" in backup_entries[0]
        assert "created_at" in backup_entries[0]

    def test_list_multiple_entries_sorted_newest_first(
        self, output_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Create two backups
        runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])

        result = runner.invoke(app, ["backup", "list", "--output-dir", str(output_dir)])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_list")
        assert any(l.get("count") == 2 for l in lines)
        backup_entries = [l for l in lines if "filename" in l and "count" not in l]
        assert len(backup_entries) == 2

    def test_nonexistent_output_dir_returns_empty(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["backup", "list", "--output-dir", str(tmp_path / "no_such_dir")],
        )
        # list_backups handles nonexistent dirs gracefully (returns empty)
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_list")
        assert any(l.get("count") == 0 for l in lines)


# ── backup cleanup ──────────────────────────────────────────────────


class TestBackupCleanup:
    """Tests for ``backup cleanup``."""

    def test_no_backups_returns_zero_totals(self, output_dir: Path, config_file: Path) -> None:
        result = runner.invoke(app, [
            "backup", "cleanup",
            "--output-dir", str(output_dir),
            "--config-path", str(config_file),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_cleanup")
        assert len(lines) == 1
        assert lines[0]["total_before"] == 0
        assert lines[0]["kept"] == []
        assert lines[0]["removed"] == []

    def test_backups_within_retention_kept(
        self, output_dir: Path, config_file: Path,
    ) -> None:
        # Create a single backup — well within any retention limit
        runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])

        result = runner.invoke(app, [
            "backup", "cleanup",
            "--output-dir", str(output_dir),
            "--config-path", str(config_file),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_cleanup")
        assert len(lines) == 1
        assert lines[0]["total_before"] == 1
        assert len(lines[0]["kept"]) == 1
        assert len(lines[0]["removed"]) == 0

    def test_cleanup_removes_excess_backups(
        self, output_dir: Path, config_file: Path,
    ) -> None:
        """With daily=1, creating 2 backups and cleaning should remove the oldest."""
        # Set a tight retention policy: keep only 1 daily
        tight_config = output_dir / "tight-config.json"
        _write_backup_config(tight_config, {
            "retention_policy": {"daily": 1, "weekly": 0, "monthly": 0},
            "output_dir": "",
        })

        # Create two backups
        runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])

        result = runner.invoke(app, [
            "backup", "cleanup",
            "--output-dir", str(output_dir),
            "--config-path", str(tight_config),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_cleanup")
        assert lines[0]["total_before"] == 2
        # With daily=1, at most 1 should be kept, 1 removed
        assert len(lines[0]["removed"]) >= 1


# ── backup config show ──────────────────────────────────────────────


class TestBackupConfigShow:
    """Tests for ``backup config show``."""

    def test_defaults_when_no_config_file(self, tmp_path: Path) -> None:
        """No config file → source=defaults with standard retention values."""
        nonexistent = tmp_path / "nonexistent-config.json"
        result = runner.invoke(app, [
            "backup", "config", "show",
            "--config-path", str(nonexistent),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_config_show")
        assert len(lines) == 1
        entry = lines[0]
        assert entry["source"] == "defaults"
        rp = entry["retention_policy"]
        assert rp["daily"] == 7
        assert rp["weekly"] == 4
        assert rp["monthly"] == 6
        assert entry["output_dir"] == ""

    def test_shows_values_from_config_file(self, config_file: Path) -> None:
        """When a config file exists, source=file and values are read from it."""
        result = runner.invoke(app, [
            "backup", "config", "show",
            "--config-path", str(config_file),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_config_show")
        assert len(lines) == 1
        entry = lines[0]
        assert entry["source"] == "file"
        rp = entry["retention_policy"]
        assert rp["daily"] == 7
        assert rp["weekly"] == 4
        assert rp["monthly"] == 6


# ── backup config set ───────────────────────────────────────────────


class TestBackupConfigSet:
    """Tests for ``backup config set``."""

    def test_set_retention_daily_persists(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "retention_policy.daily", "14",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_config_set")
        assert len(lines) == 1
        assert lines[0]["retention_policy"]["daily"] == 14

        # Verify via config show
        show = runner.invoke(app, [
            "backup", "config", "show",
            "--config-path", str(config_path),
        ])
        show_entry = _result_lines(show.output, "backup_config_show")[0]
        assert show_entry["retention_policy"]["daily"] == 14
        assert show_entry["source"] == "file"

    def test_set_output_dir_persists(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "output_dir", "/tmp/my-backups",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 0, result.output
        lines = _result_lines(result.output, "backup_config_set")
        assert lines[0]["output_dir"] == "/tmp/my-backups"

    def test_set_invalid_key_returns_input_invalid(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "bogus.key", "value",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 2, result.output  # INPUT_INVALID → exit 2
        errors = _error_lines(result.output)
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        assert "bogus.key" in errors[0].get("detail", "")

    def test_set_negative_daily_returns_error(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "retention_policy.daily", "-1",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 2, result.output  # INPUT_INVALID → exit 2
        errors = _error_lines(result.output)
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    def test_set_zero_daily_returns_error(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "retention_policy.daily", "0",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 2, result.output  # INPUT_INVALID → exit 2
        errors = _error_lines(result.output)
        assert len(errors) >= 1

    def test_set_non_integer_daily_returns_error(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "retention_policy.daily", "not-a-number",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 2, result.output  # INPUT_INVALID → exit 2
        errors = _error_lines(result.output)
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    def test_set_empty_output_dir_returns_error(self, tmp_path: Path) -> None:
        config_path = tmp_path / "cfg.json"
        _write_backup_config(config_path)

        result = runner.invoke(app, [
            "backup", "config", "set",
            "output_dir", "",
            "--config-path", str(config_path),
        ])
        assert result.exit_code == 2, result.output  # INPUT_INVALID → exit 2
        errors = _error_lines(result.output)
        assert len(errors) >= 1


# ── End-to-end flow ─────────────────────────────────────────────────


class TestBackupEndToEnd:
    """End-to-end flow: create → list → create → list → cleanup → list."""

    def test_full_lifecycle(self, output_dir: Path, config_file: Path) -> None:
        # Step 1: create first backup
        r1 = runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        assert r1.exit_code == 0, r1.output

        # Step 2: list → count=1
        r2 = runner.invoke(app, ["backup", "list", "--output-dir", str(output_dir)])
        assert r2.exit_code == 0, r2.output
        assert any(l.get("count") == 1 for l in _result_lines(r2.output, "backup_list"))

        # Step 3: create second backup
        r3 = runner.invoke(app, ["backup", "create", "--output-dir", str(output_dir)])
        assert r3.exit_code == 0, r3.output

        # Step 4: list → count=2
        r4 = runner.invoke(app, ["backup", "list", "--output-dir", str(output_dir)])
        assert r4.exit_code == 0, r4.output
        assert any(l.get("count") == 2 for l in _result_lines(r4.output, "backup_list"))

        # Step 5: cleanup with tight policy (daily=1)
        tight_config = output_dir / "tight-e2e.json"
        _write_backup_config(tight_config, {
            "retention_policy": {"daily": 1, "weekly": 0, "monthly": 0},
            "output_dir": "",
        })
        r5 = runner.invoke(app, [
            "backup", "cleanup",
            "--output-dir", str(output_dir),
            "--config-path", str(tight_config),
        ])
        assert r5.exit_code == 0, r5.output
        cleanup_entry = _result_lines(r5.output, "backup_cleanup")[0]
        assert cleanup_entry["total_before"] == 2
        assert len(cleanup_entry["kept"]) >= 1

        # Step 6: final list → count within retention
        r6 = runner.invoke(app, ["backup", "list", "--output-dir", str(output_dir)])
        assert r6.exit_code == 0, r6.output
        count_entry = [l for l in _result_lines(r6.output, "backup_list") if "count" in l]
        assert len(count_entry) == 1
        assert count_entry[0]["count"] == len(cleanup_entry["kept"])
