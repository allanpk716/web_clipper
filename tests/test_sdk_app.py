"""Tests for the SDK App singleton and error code registration."""

from __future__ import annotations

import importlib

import pytest

from web_clip_helper.app import get_app, get_writer, _init_app
from web_clip_helper.error_codes import ErrorCode, EXIT_CODE_MAP

# SDK built-in codes that must NOT be re-registered.
_BUILTIN_CODES = frozenset({
    "FATAL_CRASH",
    "INTERNAL_ERROR",
    "INPUT_INVALID",
    "NOT_FOUND",
    "RESOURCE_LOCKED",
})


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import web_clip_helper.app as mod

    old = mod._app
    mod._app = None
    yield
    mod._app = old


# ── App creation ─────────────────────────────────────────────────


class TestAppCreation:
    """Verify App singleton is created with correct metadata."""

    def test_app_name(self):
        app = get_app()
        assert app.name == "web-clip-helper"

    def test_app_version(self):
        app = get_app()
        assert app.version == "0.2.0"

    def test_singleton_identity(self):
        """get_app() always returns the same instance."""
        app1 = get_app()
        app2 = get_app()
        assert app1 is app2

    def test_get_writer_returns_app_writer(self):
        """get_writer() is a convenience that returns app.writer."""
        app = get_app()
        writer = get_writer()
        assert writer is app.writer


# ── Custom error code registration ───────────────────────────────


class TestCustomErrorCodeRegistration:
    """Verify all custom error codes resolve to correct exit codes."""

    @pytest.mark.parametrize(
        "code, expected_exit",
        # Only custom (non-built-in) codes from EXIT_CODE_MAP.
        [
            ("STORAGE_ERROR", 3),
            ("INDEX_ERROR", 3),
            ("NETWORK_ERROR", 4),
            ("FETCH_ERROR", 4),
            ("ROUTING_ERROR", 4),
            ("URL_ROUTE_ERROR", 4),
            ("TIMEOUT_ERROR", 4),
            ("CONFIG_ERROR", 2),
            ("REFRESH_ERROR", 3),
            ("INVALID_TYPE", 2),
            ("NO_CUSTOM_PROMPT", 2),
        ],
        ids=lambda v: v if isinstance(v, str) else str(v),
    )
    def test_custom_code_exit_mapping(self, code, expected_exit):
        app = get_app()
        assert app.error_code_to_exit_code(code) == expected_exit

    def test_all_custom_codes_registered(self):
        """Every non-built-in EXIT_CODE_MAP entry is registered."""
        app = get_app()
        custom_codes = {
            k: v for k, v in EXIT_CODE_MAP.items()
            if k not in _BUILTIN_CODES
        }
        registry = app._registry.all_codes()
        for code in custom_codes:
            assert code in registry, f"Custom code {code!r} missing from registry"


# ── SDK built-in codes ──────────────────────────────────────────


class TestBuiltInCodes:
    """Verify SDK built-in codes are present and resolve correctly."""

    @pytest.mark.parametrize(
        "code, expected_exit",
        [
            ("FATAL_CRASH", 1),
            ("INTERNAL_ERROR", 1),
            ("INPUT_INVALID", 2),
            ("NOT_FOUND", 3),
            ("RESOURCE_LOCKED", 5),
        ],
    )
    def test_builtin_code_present(self, code, expected_exit):
        app = get_app()
        assert app.error_code_to_exit_code(code) == expected_exit

    def test_unknown_code_returns_fatal(self):
        """Unknown codes fall back to EXIT_FATAL_ERROR (1)."""
        app = get_app()
        assert app.error_code_to_exit_code("COMPLETELY_UNKNOWN_CODE") == 1
