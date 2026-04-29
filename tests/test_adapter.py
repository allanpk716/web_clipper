"""Tests for the adapter framework — BaseAdapter, router, registration."""

from __future__ import annotations

import pytest
import httpx

from web_clip_helper.adapter import (
    AdapterError,
    BaseAdapter,
    _GenericAdapter,
    adapter_router,
    register_adapter,
    route_url,
)
from web_clip_helper.models import RawContent


# ── Fixtures ─────────────────────────────────────────────────────────


class StubAdapter(BaseAdapter):
    """Concrete adapter for testing."""

    source_type = "stub"

    def fetch(self, url: str) -> RawContent:
        return RawContent(
            url=url,
            title="Stub",
            content_md="# Stub content",
            source_type=self.source_type,
        )


@pytest.fixture(autouse=True)
def _clean_router():
    """Clear the global router before/after each test to avoid cross-contamination."""
    saved = adapter_router.copy()
    adapter_router.clear()
    yield
    adapter_router.clear()
    adapter_router.extend(saved)


# ── BaseAdapter contract ────────────────────────────────────────────


class TestBaseAdapter:
    def test_cannot_instantiate_directly(self):
        """BaseAdapter is abstract — must subclass."""
        with pytest.raises(TypeError):
            BaseAdapter()  # type: ignore[abstract]

    def test_subclass_must_implement_fetch(self):
        """A subclass without fetch() cannot be instantiated."""

        class Incomplete(BaseAdapter):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_subclass_works(self):
        adapter = StubAdapter()
        result = adapter.fetch("https://example.com")
        assert isinstance(result, RawContent)
        assert result.url == "https://example.com"
        assert result.source_type == "stub"


# ── Registration and routing ────────────────────────────────────────


class TestRegisterAdapter:
    def test_register_and_route(self):
        """Registered adapter is returned by route_url for matching URLs."""
        register_adapter(r"https://example\.com/.*", StubAdapter)
        assert route_url("https://example.com/page") is StubAdapter

    def test_register_returns_class(self):
        """register_adapter returns the class (decorator pattern)."""
        result = register_adapter(r"https://test\.com", StubAdapter)
        assert result is StubAdapter

    def test_no_match_returns_generic(self):
        """When no pattern matches, the generic fallback is returned."""
        assert route_url("https://unknown-site.com/page") is _GenericAdapter

    def test_first_match_wins(self):
        """When multiple patterns match, the first registered wins."""

        class AlphaAdapter(BaseAdapter):
            source_type = "alpha"

            def fetch(self, url: str) -> RawContent:
                return RawContent(url=url, title="", content_md="", source_type="alpha")

        class BetaAdapter(BaseAdapter):
            source_type = "beta"

            def fetch(self, url: str) -> RawContent:
                return RawContent(url=url, title="", content_md="", source_type="beta")

        register_adapter(r"https://x\.com/.*", AlphaAdapter)
        register_adapter(r"https://x\.com/special", BetaAdapter)

        assert route_url("https://x.com/special") is AlphaAdapter

    def test_case_insensitive_matching(self):
        """Patterns match regardless of URL case."""
        register_adapter(r"https://example\.com", StubAdapter)
        assert route_url("HTTPS://EXAMPLE.COM/page") is StubAdapter

    def test_empty_url_raises(self):
        """Empty or None URL raises ValueError."""
        with pytest.raises(ValueError, match="Invalid URL"):
            route_url("")
        with pytest.raises(ValueError, match="Invalid URL"):
            route_url("")  # Can't pass None — it's typed as str

    def test_whitespace_url_raises(self):
        with pytest.raises(ValueError, match="Invalid URL"):
            route_url("   ")


# ── Generic adapter ─────────────────────────────────────────────────


class TestGenericAdapter:
    def test_delegates_to_real_implementation(self):
        """Generic adapter delegates to GenericWebAdapter (not a placeholder)."""
        adapter = _GenericAdapter()
        # source_type should now be "web" (delegated)
        assert adapter.source_type == "web"

    def test_raises_on_genuine_fetch_failure(self):
        """Generic adapter raises AdapterError when fetch actually fails."""
        from unittest.mock import patch

        adapter = _GenericAdapter()
        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_client:
            mock_client.return_value.__enter__ = lambda s: s
            mock_client.return_value.__exit__ = lambda s, *a: None
            mock_client.return_value.get.side_effect = httpx.ConnectError("no network")
            with pytest.raises(AdapterError, match="Failed to fetch"):
                adapter.fetch("https://nonexistent.invalid/page")
