"""Adapter framework — BaseAdapter, URL pattern router, registration.

Adapters are registered against URL patterns (compiled regex).  When a URL
needs clipping, ``route_url()`` walks the patterns in registration order and
returns the first matching adapter class.  If nothing matches, the generic
adapter is used as the fallback.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from .models import RawContent

__all__ = [
    "BaseAdapter",
    "adapter_router",
    "register_adapter",
    "route_url",
]


class BaseAdapter(ABC):
    """Abstract base for all content adapters.

    Subclasses must implement ``fetch(url) -> RawContent`` and set a
    ``source_type`` class attribute that identifies the platform.
    """

    source_type: str = "generic"

    @abstractmethod
    def fetch(self, url: str) -> RawContent:
        """Fetch *url* and return parsed raw content.

        Parameters
        ----------
        url:
            The fully-qualified URL to clip.

        Returns
        -------
        RawContent
            Parsed content including markdown body and image URLs.

        Raises
        ------
        AdapterError
            If the URL cannot be fetched or parsed.
        """
        ...  # pragma: no cover


class AdapterError(Exception):
    """Raised when an adapter fails to fetch or parse a URL."""


# ── URL pattern router ──────────────────────────────────────────────

# Global ordered list of (compiled_pattern, adapter_class).
# Using a list (not dict) to preserve registration order.
adapter_router: list[tuple[re.Pattern[str], type[BaseAdapter]]] = []


def register_adapter(pattern: str, adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
    """Register *adapter_cls* for URLs matching *pattern*.

    Can be used as a decorator::

        @register_adapter(r"https://github\\.com/.*")
        class GitHubAdapter(BaseAdapter): ...

    Parameters
    ----------
    pattern:
        A regex pattern that will be compiled with ``re.IGNORECASE``.
    adapter_cls:
        The adapter class to register.

    Returns
    -------
    type[BaseAdapter]
        The same class, unmodified (enables decorator use).
    """
    compiled = re.compile(pattern, re.IGNORECASE)
    adapter_router.append((compiled, adapter_cls))
    return adapter_cls


def route_url(url: str) -> type[BaseAdapter]:
    """Return the adapter class registered for *url*.

    Walks ``adapter_router`` in registration order.  Returns the first
    match.  If no pattern matches, returns a generic fallback adapter
    class (``_GenericAdapter``).

    Raises
    ------
    ValueError
        If *url* is empty or not a string.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError(f"Invalid URL: {url!r}")

    for pattern, cls in adapter_router:
        if pattern.search(url):
            return cls

    # Fallback to generic
    return _GenericAdapter


# ── Generic fallback adapter (placeholder) ──────────────────────────

# Will be replaced by a real implementation in a later slice, but we
# need a concrete class here so that route_url() always returns something
# usable.

class _GenericAdapter(BaseAdapter):
    """Fallback adapter that attempts generic HTML-to-markdown conversion."""

    source_type = "generic"

    def fetch(self, url: str) -> RawContent:
        from .output import jsonl_emit_error

        jsonl_emit_error(
            stage="adapter",
            detail=f"No specific adapter for URL: {url}. "
                   "Generic adapter is not yet implemented.",
        )
        raise AdapterError(
            f"Generic adapter not yet implemented for URL: {url}"
        )
