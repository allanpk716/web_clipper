"""Global I/O guard — hijack sys.stdout/stderr so third-party print() is silently captured.

At app startup (inside ``_JSONLGroup.main()``), call ``init_io_guard()`` to
replace ``sys.stdout`` and ``sys.stderr`` with memory-backed ``_FakeStream``
instances.  All JSONL output should be written through ``get_real_stdout()``
instead of ``sys.stdout`` so it reaches the real terminal / CliRunner capture,
bypassing the fake buffer.

The fake streams delegate attribute access (``encoding``, ``reconfigure``,
``isatty``, ``fileno``, ``buffer``, etc.) to the real stdout/stderr for
Click/Rich compatibility.
"""

from __future__ import annotations

import io
import sys
from typing import Any

__all__ = [
    "init_io_guard",
    "get_real_stdout",
    "get_real_stderr",
    "get_captured_stdout",
    "get_captured_stderr",
    "clear_captured",
    "teardown",
]

# ── Module-level state ──────────────────────────────────────────────

_real_stdout: Any | None = None
_real_stderr: Any | None = None
_fake_stdout: _FakeStream | None = None
_fake_stderr: _FakeStream | None = None


# ── Fake stream ─────────────────────────────────────────────────────


class _FakeStream:
    """A write-only memory buffer that delegates unknown attribute access to the real stream.

    Uses composition (not inheritance) so that attributes like ``encoding``,
    ``isatty``, ``fileno``, ``buffer``, and ``reconfigure`` are all delegated
    to the real stream without being shadowed by a StringIO parent class.

    Only the methods needed for capturing output (``write``, ``getvalue``,
    ``truncate``, ``seek``, ``flush``) are implemented locally.
    """

    def __init__(self, real_stream: Any) -> None:
        object.__setattr__(self, "_buffer", io.StringIO())
        object.__setattr__(self, "_real", real_stream)

    def write(self, text: str) -> int:
        return object.__getattribute__(self, "_buffer").write(text)

    def getvalue(self) -> str:
        return object.__getattribute__(self, "_buffer").getvalue()

    def truncate(self, size: int | None = None) -> int:
        return object.__getattribute__(self, "_buffer").truncate(size)

    def seek(self, pos: int, whence: int = 0) -> int:
        return object.__getattribute__(self, "_buffer").seek(pos, whence)

    def flush(self) -> None:
        """No-op for the capture buffer; real stream flushes independently."""
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_real"), name)


# ── Public API ──────────────────────────────────────────────────────


def init_io_guard() -> None:
    """Replace ``sys.stdout`` and ``sys.stderr`` with fake memory buffers.

    Idempotent — if ``sys.stdout`` is already our fake stream, this is a
    no-op.  If ``sys.stdout`` has changed since the last call (e.g. a test
    runner replaced it), the guard reinitializes with the new stream.
    """
    global _real_stdout, _real_stderr, _fake_stdout, _fake_stderr

    # Already active and sys.stdout hasn't been swapped out → no-op.
    if _fake_stdout is not None and sys.stdout is _fake_stdout:
        return

    _real_stdout = sys.stdout
    _real_stderr = sys.stderr
    _fake_stdout = _FakeStream(_real_stdout)
    _fake_stderr = _FakeStream(_real_stderr)
    sys.stdout = _fake_stdout
    sys.stderr = _fake_stderr


def get_real_stdout() -> Any:
    """Return the saved real stdout, or ``sys.stdout`` if the guard is inactive.

    When the guard is active and consistent (``sys.stdout`` is still our fake),
    this returns the original stream that was saved before hijacking.  When
    inactive or inconsistent (an external party like CliRunner restored
    ``sys.stdout``), it falls back to ``sys.stdout`` so behaviour is unchanged.
    """
    if _fake_stdout is not None and sys.stdout is _fake_stdout:
        return _real_stdout
    return sys.stdout


def get_real_stderr() -> Any:
    """Return the saved real stderr, or ``sys.stderr`` if the guard is inactive."""
    if _fake_stderr is not None and sys.stderr is _fake_stderr:
        return _real_stderr
    return sys.stderr


def get_captured_stdout() -> str:
    """Return everything written to the fake stdout buffer so far.

    Useful for detecting Click help text (non-JSONL output) that was rendered
    to stdout before the exception handler could intercept it.
    """
    if _fake_stdout is not None:
        return _fake_stdout.getvalue()
    return ""


def get_captured_stderr() -> str:
    """Return everything written to the fake stderr buffer so far."""
    if _fake_stderr is not None:
        return _fake_stderr.getvalue()
    return ""


def clear_captured() -> None:
    """Clear both fake buffers (stdout and stderr)."""
    if _fake_stdout is not None:
        _fake_stdout.truncate(0)
        _fake_stdout.seek(0)
    if _fake_stderr is not None:
        _fake_stderr.truncate(0)
        _fake_stderr.seek(0)


def teardown() -> None:
    """Restore ``sys.stdout`` and ``sys.stderr`` to their original streams.

    Resets all module-level state so a subsequent ``init_io_guard()`` starts
    fresh.
    """
    global _real_stdout, _real_stderr, _fake_stdout, _fake_stderr

    if _real_stdout is not None:
        sys.stdout = _real_stdout
    if _real_stderr is not None:
        sys.stderr = _real_stderr

    _real_stdout = None
    _real_stderr = None
    _fake_stdout = None
    _fake_stderr = None
