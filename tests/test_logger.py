"""Tests for the logger module — init_logger, get_logger, close_logger."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from web_clip_helper.logger import close_logger, get_logger, init_logger


class TestInitLogger:
    """Tests for init_logger()."""

    def setup_method(self) -> None:
        """Reset module state before each test."""
        close_logger()

    def teardown_method(self) -> None:
        """Clean up after each test."""
        close_logger()

    def test_init_logger_returns_sdk_logger(self) -> None:
        """init_logger() should return an agentsdk.Logger instance."""
        logger = init_logger()
        import agentsdk

        assert isinstance(logger, agentsdk.Logger)

    def test_init_logger_idempotent(self) -> None:
        """Calling init_logger() twice should return the same instance."""
        first = init_logger()
        second = init_logger()
        assert first is second

    def test_init_logger_removes_stderr_handler(self) -> None:
        """After init_logger(), the SDK logger should have no stderr handler."""
        logger = init_logger()
        assert logger._stderr_handler is None

    def test_init_logger_keeps_file_handler(self) -> None:
        """After init_logger(), the SDK logger should retain its file handler."""
        logger = init_logger()
        assert logger._file_handler is not None

    def test_init_logger_creates_log_file(self) -> None:
        """init_logger() should create the log file in the sandbox logs dir."""
        import agentsdk

        sandbox = agentsdk.Sandbox("web-clip-helper")
        logs_dir = Path(sandbox.logs_dir)

        logger = init_logger()
        log_file = logs_dir / "web-clip-helper.log"

        # The log file may not exist until a message is written
        # (TimedRotatingFileHandler creates on first emit), so log a message.
        logger.info("test log message")
        assert log_file.exists()

    def test_init_logger_file_content_format(self) -> None:
        """Log file should contain structured output with expected format."""
        import agentsdk

        sandbox = agentsdk.Sandbox("web-clip-helper")
        logs_dir = Path(sandbox.logs_dir)
        log_file = logs_dir / "web-clip-helper.log"

        logger = init_logger()
        logger.info("format test message")

        content = log_file.read_text(encoding="utf-8")
        assert "[INFO]" in content
        assert "format test message" in content


class TestGetLogger:
    """Tests for get_logger()."""

    def test_get_logger_returns_stdlib_logger(self) -> None:
        """get_logger() should return a stdlib logging.Logger."""
        logger = get_logger()
        assert isinstance(logger, logging.Logger)

    def test_get_logger_default_name(self) -> None:
        """get_logger() with no args should use 'web_clip_helper'."""
        logger = get_logger()
        assert logger.name == "web_clip_helper"

    def test_get_logger_custom_name(self) -> None:
        """get_logger(name='foo') should return a logger named 'foo'."""
        logger = get_logger("foo")
        assert logger.name == "foo"


class TestCloseLogger:
    """Tests for close_logger()."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_close_logger_after_init(self) -> None:
        """close_logger() after init_logger() should release resources."""
        logger = init_logger()
        error = close_logger()
        assert error is None

    def test_close_logger_without_init(self) -> None:
        """close_logger() without init_logger() should be safe (no-op)."""
        error = close_logger()
        assert error is None

    def test_close_logger_idempotent(self) -> None:
        """Calling close_logger() twice should be safe."""
        init_logger()
        close_logger()
        error = close_logger()
        assert error is None

    def test_reinit_after_close(self) -> None:
        """init_logger() should work again after close_logger()."""
        first = init_logger()
        close_logger()
        second = init_logger()
        assert second is not first


class TestNullHandlerSuppression:
    """Tests for third-party library NullHandler suppression (MEM010)."""

    def setup_method(self) -> None:
        close_logger()

    def teardown_method(self) -> None:
        close_logger()

    def test_third_party_loggers_get_null_handler(self) -> None:
        """init_logger() should add NullHandler to known third-party loggers."""
        # Remove any pre-existing handlers for clean test
        for lib in ("openai", "httpx", "httpcore"):
            lib_logger = logging.getLogger(lib)
            lib_logger.handlers = [
                h for h in lib_logger.handlers
                if not isinstance(h, logging.NullHandler)
            ]

        init_logger()

        for lib in ("web_clip_helper", "openai", "httpx", "httpcore"):
            lib_logger = logging.getLogger(lib)
            has_null = any(isinstance(h, logging.NullHandler) for h in lib_logger.handlers)
            assert has_null, f"{lib} should have a NullHandler after init_logger()"
