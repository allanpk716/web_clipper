"""Integration tests for Logger module — end-to-end file logging, CLI integration, and stderr hygiene.

Verifies:
1. Logger creates log file on init
2. Log file has SDK format (YYYY-MM-DD HH:MM:SS.mmm - [LEVEL]: message)
3. with_field produces key=value pairs
4. close_logger() cleans up
5. init is idempotent
6. --quiet clip --text produces log file
7. --quiet mode stderr is empty
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.logger import close_logger, init_logger

runner = CliRunner()

# Log format regex: 2026-05-11 21:25:03.949 - [INFO]: message key=value
_LOG_FORMAT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} - \[(DEBUG|INFO|WARN|WARNING|ERROR)\]: .+"
)


def _get_log_file_path() -> Path:
    """Return the expected log file path for the web-clip-helper sandbox."""
    import agentsdk

    sandbox = agentsdk.Sandbox("web-clip-helper")
    return Path(sandbox.logs_dir) / "web-clip-helper.log"


def _read_log_file() -> str:
    """Read the current log file contents (empty string if missing)."""
    log_file = _get_log_file_path()
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


class TestLogFileCreation:
    """(1) Logger creates log file on init."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_init_creates_log_file(self) -> None:
        """init_logger() + writing a message should create the log file."""
        log_file = _get_log_file_path()
        # Log file may exist from previous runs; note its size before
        size_before = log_file.stat().st_size if log_file.exists() else 0

        logger = init_logger()
        logger.info("integration test: log file creation")

        assert log_file.exists(), "Log file should exist after init_logger() + info()"
        size_after = log_file.stat().st_size
        assert size_after > size_before, "Log file should grow after writing a message"


class TestLogFormat:
    """(2) Log file has SDK format (YYYY-MM-DD HH:MM:SS.mmm - [LEVEL]: message)."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_log_file_matches_sdk_format(self) -> None:
        """Each log line should match the expected SDK timestamp format."""
        logger = init_logger()
        marker = "FORMAT_TEST_MARKER_UNIQUE_12345"
        logger.info(marker)

        content = _read_log_file()
        assert marker in content, "Marker should appear in log file"

        # Find the line with our marker and verify format
        for line in content.strip().splitlines():
            if marker in line:
                assert _LOG_FORMAT_RE.match(line), (
                    f"Log line does not match SDK format: {line!r}"
                )
                return
        pytest.fail(f"Marker {marker!r} not found in log file")

    def test_log_file_contains_level_brackets(self) -> None:
        """Log lines should contain [INFO], [ERROR], etc."""
        logger = init_logger()
        marker = "LEVEL_BRACKET_TEST"
        logger.info(marker)

        content = _read_log_file()
        assert "[INFO]" in content, "Log should contain [INFO] level bracket"


class TestWithField:
    """(3) with_field produces key=value pairs."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_single_field_key_value(self) -> None:
        """with_field('cmd', 'clip') should append cmd=clip to the log line."""
        logger = init_logger()
        marker = "WITH_FIELD_SINGLE_TEST"
        logger.with_field("cmd", "clip").info(marker)

        content = _read_log_file()
        for line in content.strip().splitlines():
            if marker in line:
                assert "cmd=clip" in line, f"Expected 'cmd=clip' in: {line!r}"
                return
        pytest.fail(f"Marker {marker!r} not found in log file")

    def test_chained_with_fields(self) -> None:
        """Chained with_field() calls should append multiple key=value pairs."""
        logger = init_logger()
        marker = "WITH_FIELD_CHAIN_TEST"
        logger.with_field("cmd", "clip").with_field("status", "ok").info(marker)

        content = _read_log_file()
        for line in content.strip().splitlines():
            if marker in line:
                assert "cmd=clip" in line, f"Expected 'cmd=clip' in: {line!r}"
                assert "status=ok" in line, f"Expected 'status=ok' in: {line!r}"
                return
        pytest.fail(f"Marker {marker!r} not found in log file")

    def test_with_fields_dict(self) -> None:
        """with_fields() with a dict should append multiple key=value pairs."""
        logger = init_logger()
        marker = "WITH_FIELDS_DICT_TEST"
        logger.with_fields({"action": "delete", "id": 42}).info(marker)

        content = _read_log_file()
        for line in content.strip().splitlines():
            if marker in line:
                assert "action=delete" in line, f"Expected 'action=delete' in: {line!r}"
                assert "id=42" in line, f"Expected 'id=42' in: {line!r}"
                return
        pytest.fail(f"Marker {marker!r} not found in log file")


class TestCloseLogger:
    """(4) close_logger() cleans up."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_close_returns_none_on_success(self) -> None:
        """close_logger() after init should return None (success)."""
        init_logger()
        error = close_logger()
        assert error is None

    def test_close_releases_file_handle(self) -> None:
        """After close_logger(), re-init should work (file handle released)."""
        first = init_logger()
        close_logger()
        second = init_logger()
        assert second is not first, "Re-init after close should create a new logger"


class TestIdempotentInit:
    """(5) init is idempotent."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_init_returns_same_instance(self) -> None:
        """Multiple init_logger() calls should return the same instance."""
        first = init_logger()
        second = init_logger()
        third = init_logger()
        assert first is second is third

    def test_init_does_not_duplicate_handlers(self) -> None:
        """Idempotent init should not add duplicate NullHandlers."""
        # Clean third-party handlers first
        for lib in ("openai", "httpx", "httpcore", "web_clip_helper"):
            logging.getLogger(lib).handlers = []

        init_logger()
        init_logger()
        init_logger()

        lib_logger = logging.getLogger("openai")
        null_count = sum(
            1 for h in lib_logger.handlers if isinstance(h, logging.NullHandler)
        )
        assert null_count == 1, (
            f"Expected exactly 1 NullHandler, got {null_count} "
            f"(total handlers: {lib_logger.handlers})"
        )


class TestQuietClipTextLog:
    """(6) --quiet clip --text produces log file."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_quiet_clip_text_creates_log_file(self) -> None:
        """Running clip --text with --quiet should still initialize the logger and create its log file."""
        log_file = _get_log_file_path()
        # Remove log file so we can verify it's freshly created by the CLI
        if log_file.exists():
            log_file.unlink()

        result = runner.invoke(
            app, ["--quiet", "clip", "--text", "logger integration test content"]
        )
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"

        # The SDK Logger's TimedRotatingFileHandler creates the log file
        # when initialized, even before any messages are written.
        assert log_file.exists(), (
            "Log file should be created by init_logger() during CLI startup"
        )


class TestQuietStderrClean:
    """(7) --quiet mode stderr is empty."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_quiet_version_stderr_clean(self) -> None:
        """--quiet version should produce nothing on stderr."""
        result = runner.invoke(app, ["--quiet", "version"])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"
        # CliRunner captures stderr via result.stderr on newer versions,
        # but Typer merges into result.output. Check for no log-like lines.
        for line in result.output.strip().splitlines():
            # Should only be JSONL lines (start with {), not bare log lines
            if line.strip():
                assert line.strip().startswith("{"), (
                    f"Non-JSONL line on output in --quiet mode: {line!r}"
                )

    def test_quiet_list_stderr_clean(self) -> None:
        """--quiet list should not have bare log lines on output."""
        result = runner.invoke(app, ["--quiet", "list"])
        assert result.exit_code == 0, f"Exit {result.exit_code}: {result.exception}"
        for line in result.output.strip().splitlines():
            if line.strip():
                assert line.strip().startswith("{"), (
                    f"Non-JSONL line on output in --quiet mode: {line!r}"
                )

    def test_third_party_loggers_have_null_handler(self) -> None:
        """After CLI run, third-party loggers should still have NullHandler."""
        # Run a command to trigger init_logger via CLI
        runner.invoke(app, ["--quiet", "version"])

        for lib in ("openai", "httpx", "httpcore", "web_clip_helper"):
            lib_logger = logging.getLogger(lib)
            has_null = any(
                isinstance(h, logging.NullHandler) for h in lib_logger.handlers
            )
            assert has_null, f"{lib} should have NullHandler after CLI execution"
