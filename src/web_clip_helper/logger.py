"""Logger module — file-only structured logging via agentsdk.

Provides ``init_logger()``, ``get_logger()``, and ``close_logger()`` as the
public API.  Uses ``agentsdk.Sandbox`` to resolve the logs directory, then
creates an ``agentsdk.Logger`` and immediately removes its stderr handler
(D004 — file-only logging).

Typical usage (called once at CLI startup)::

    from web_clip_helper.logger import init_logger, close_logger

    init_logger()          # set up file-only logger
    ...                    # app runs ...
    close_logger()         # flush & release handlers
"""

from __future__ import annotations

import logging
from typing import Optional

import agentsdk

__all__ = ["init_logger", "get_logger", "close_logger"]

# ── Module-level state ──────────────────────────────────────────────

_sdk_logger: Optional[agentsdk.Logger] = None
_initialized = False

# ── Public API ──────────────────────────────────────────────────────


def init_logger() -> agentsdk.Logger:
    """Create and configure the file-only SDK logger.

    Uses ``agentsdk.Sandbox("web-clip-helper")`` to get the logs directory,
    creates an ``agentsdk.Logger`` with default settings, then removes the
    stderr handler so only the file handler remains (D004).

    Idempotent — calling this multiple times returns the existing logger
    without re-creating it.

    Returns:
        The initialized :class:`agentsdk.Logger` instance.
    """
    global _sdk_logger, _initialized

    if _initialized and _sdk_logger is not None:
        return _sdk_logger

    sandbox = agentsdk.Sandbox("web-clip-helper")
    settings = agentsdk.default_logger_settings("web-clip-helper", sandbox.logs_dir)
    _sdk_logger = agentsdk.Logger(settings)

    # D004: Remove stderr handler — keep file-only logging.
    # The SDK Logger stores its handlers as _stderr_handler and _file_handler
    # on the internal logger.  Remove the stderr handler so --quiet mode
    # stays clean.
    if _sdk_logger._stderr_handler is not None:
        _sdk_logger._internal_logger.removeHandler(_sdk_logger._stderr_handler)
        try:
            _sdk_logger._stderr_handler.close()
        except Exception:
            pass
        _sdk_logger._stderr_handler = None

    _initialized = True

    # Suppress third-party library stderr log leakage (MEM010).
    # These libraries use stdlib logging and default to stderr when no
    # handler is configured.  Adding NullHandler prevents this without
    # affecting the SDK file-only logger.
    for _lib in ("web_clip_helper", "openai", "httpx", "httpcore"):
        _lib_logger = logging.getLogger(_lib)
        if not _lib_logger.handlers:
            _lib_logger.addHandler(logging.NullHandler())

    return _sdk_logger


def get_logger(name: str = "web_clip_helper") -> logging.Logger:
    """Return a stdlib :class:`logging.Logger` for the given *name*.

    The returned logger propagates to the root logger.  Because the SDK
    Logger uses an internal ``agentsdk.{id}`` logger with ``propagate=False``,
    callers who want structured file output should use the SDK logger directly
    (via ``init_logger()``) or use this function for ad-hoc stdlib logging
    that is captured by any root-level handler.

    Args:
        name: Logger name (default ``"web_clip_helper"``).

    Returns:
        A stdlib :class:`logging.Logger`.
    """
    return logging.getLogger(name)


def close_logger() -> Optional[str]:
    """Release all handler resources on the SDK logger.

    Safe to call even if ``init_logger()`` was never called.

    Returns:
        An error description string if any handler failed to close,
        or ``None`` on success.
    """
    global _sdk_logger, _initialized

    if _sdk_logger is not None:
        error = _sdk_logger.close()
        _sdk_logger = None
        _initialized = False
        return error
    return None
