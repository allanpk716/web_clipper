"""Adapter framework — BaseAdapter, URL pattern router, registration.

Adapters are registered against URL patterns (compiled regex).  When a URL
needs clipping, ``route_url()`` walks the patterns in registration order and
returns the first matching adapter class.  If nothing matches, the generic
adapter is used as the fallback.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Callable

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


def register_adapter(
    pattern: str,
    adapter_cls: type[BaseAdapter] | None = None,
) -> type[BaseAdapter] | Callable[[type[BaseAdapter]], type[BaseAdapter]]:
    """Register *adapter_cls* for URLs matching *pattern*.

    Can be used as a decorator factory::

        @register_adapter(r"https://github\\.com/.*")
        class GitHubAdapter(BaseAdapter): ...

    Or called directly::

        register_adapter(r"https://github\\.com/.*", GitHubAdapter)

    Parameters
    ----------
    pattern:
        A regex pattern that will be compiled with ``re.IGNORECASE``.
    adapter_cls:
        The adapter class to register.  If ``None``, returns a decorator.

    Returns
    -------
    type[BaseAdapter] or callable
        The same class, unmodified (enables decorator use), or a
        decorator function if *adapter_cls* is ``None``.
    """
    compiled = re.compile(pattern, re.IGNORECASE)

    def _decorator(cls: type[BaseAdapter]) -> type[BaseAdapter]:
        adapter_router.append((compiled, cls))
        return cls

    if adapter_cls is not None:
        return _decorator(adapter_cls)

    return _decorator


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


# ── Generic fallback adapter ─────────────────────────────────────────

# Lazy import to avoid circular dependency — the real implementation
# lives in adapters/generic.py.  We fall back to a minimal stub only
# if the adapters package is not yet available (e.g. during early import).


class _GenericAdapter(BaseAdapter):
    """Fallback adapter — delegates to the real GenericWebAdapter.

    On first use, imports the concrete implementation from
    ``adapters.generic``.  This avoids circular imports at module level.
    """

    source_type = "web"
    _real_adapter = None  # type: ignore[assignment]

    def _get_adapter(self):  # type: ignore[type-arg]
        if self.__class__._real_adapter is None:
            from .adapters.generic import GenericWebAdapter

            self.__class__._real_adapter = GenericWebAdapter()
        return self.__class__._real_adapter

    def fetch(self, url: str) -> RawContent:
        return self._get_adapter().fetch(url)
