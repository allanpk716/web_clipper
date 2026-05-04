"""Tests for the global I/O guard (io_guard module).

Validates that:
- init_io_guard() hijacks sys.stdout/stderr so print() is captured
- jsonl_emit() writes through get_real_stdout() to the real stream
- Third-party output is available via get_captured_stdout()
- The guard is idempotent and can be torn down cleanly
- Attribute delegation works for Click/Rich compatibility
"""

from __future__ import annotations

import io
import json
import sys

import pytest

from web_clip_helper.io_guard import (
    clear_captured,
    get_captured_stderr,
    get_captured_stdout,
    get_real_stderr,
    get_real_stdout,
    init_io_guard,
    teardown,
)
from web_clip_helper.output import jsonl_emit


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_guard():
    """Ensure the I/O guard is fully reset before and after each test."""
    teardown()
    yield
    teardown()


# ── Core behaviour ──────────────────────────────────────────────────


class TestInitSwallowsPrint:
    """Third-party print() calls are captured, not sent to real stdout."""

    def test_print_does_not_reach_real_stdout(self) -> None:
        original = sys.stdout
        init_io_guard()

        # Third-party noise
        print("noise from some library")
        print("more noise")

        # jsonl_emit should still reach real stdout
        jsonl_emit("progress", message="real output")

        # Verify: real stdout got the JSONL but NOT the noise
        real_output = get_real_stdout().getvalue() if hasattr(get_real_stdout(), "getvalue") else ""
        # When io_guard is active, get_real_stdout() is the original stream.
        # In this test, original is a StringIO (pytest captures), so:
        #   - jsonl_emit wrote to get_real_stdout() = original StringIO
        #   - print() wrote to sys.stdout = fake buffer
        assert "noise" not in real_output

        # Verify: captured buffer has the noise
        captured = get_captured_stdout()
        assert "noise from some library" in captured
        assert "more noise" in captured

    def test_only_jsonl_in_real_stdout(self) -> None:
        """Real stdout should contain only JSONL lines, no third-party output."""
        # Use a StringIO as the "real" stdout so we can read it back
        real_out = io.StringIO()
        sys.stdout = real_out
        try:
            init_io_guard()

            print("third-party noise")
            jsonl_emit("result", stage="test", status="ok")

            # Read what reached the real stdout
            real_content = real_out.getvalue()
            lines = [l for l in real_content.strip().splitlines() if l.strip()]
            # Only the JSONL line should be there
            assert len(lines) == 1
            obj = json.loads(lines[0])
            assert obj["type"] == "result"
            assert obj["stage"] == "test"
            assert "noise" not in real_content
        finally:
            teardown()


class TestJsonlEmitReachesRealStdout:
    """jsonl_emit writes through get_real_stdout() to the real stream."""

    def test_emit_goes_to_real_stdout(self) -> None:
        real_out = io.StringIO()
        sys.stdout = real_out
        try:
            init_io_guard()

            jsonl_emit("progress", message="hello")

            real_content = real_out.getvalue()
            assert real_content.strip()
            obj = json.loads(real_content.strip())
            assert obj["type"] == "progress"
            assert obj["message"] == "hello"
        finally:
            teardown()


class TestGetCapturedStdout:
    """get_captured_stdout() returns third-party output."""

    def test_returns_third_party_output(self) -> None:
        init_io_guard()

        print("hello from third-party")
        print("another line")

        captured = get_captured_stdout()
        assert "hello from third-party" in captured
        assert "another line" in captured

    def test_empty_when_no_output(self) -> None:
        init_io_guard()
        assert get_captured_stdout() == ""

    def test_empty_when_guard_inactive(self) -> None:
        # Without init, get_captured_stdout returns ""
        assert get_captured_stdout() == ""


class TestIdempotentInit:
    """init_io_guard() can be called twice without error."""

    def test_double_init_no_error(self) -> None:
        init_io_guard()
        init_io_guard()  # should be a no-op
        print("test")
        assert "test" in get_captured_stdout()

    def test_double_init_preserves_state(self) -> None:
        """Second init doesn't create new fakes — same fake is kept."""
        init_io_guard()
        print("first")
        init_io_guard()  # no-op
        print("second")
        captured = get_captured_stdout()
        assert "first" in captured
        assert "second" in captured

    def test_reinit_when_stdout_changed(self) -> None:
        """If sys.stdout changed externally, reinitialize."""
        init_io_guard()
        # Simulate external change (e.g. test runner replacing stdout)
        new_stdout = io.StringIO()
        sys.stdout = new_stdout
        init_io_guard()  # should reinitialize with new_stdout
        print("reinit output")
        # Captured output from NEW fake (wrapping new_stdout)
        assert "reinit output" in get_captured_stdout()


class TestTeardownRestoresStreams:
    """teardown() restores original sys.stdout and sys.stderr."""

    def test_restore_stdout(self) -> None:
        original = sys.stdout
        init_io_guard()
        assert sys.stdout is not original
        teardown()
        assert sys.stdout is original

    def test_restore_stderr(self) -> None:
        original = sys.stderr
        init_io_guard()
        assert sys.stderr is not original
        teardown()
        assert sys.stderr is original

    def test_teardown_resets_state(self) -> None:
        """After teardown, get_real_stdout falls back to sys.stdout."""
        init_io_guard()
        real = get_real_stdout()
        teardown()
        assert get_real_stdout() is sys.stdout


class TestInactiveGuardFallback:
    """Without init, jsonl_emit writes to sys.stdout (test compat)."""

    def test_fallback_without_init(self, capsys) -> None:
        # Don't call init_io_guard — guard is inactive
        jsonl_emit("result", test=True)

        captured = capsys.readouterr()
        obj = json.loads(captured.out.strip())
        assert obj["type"] == "result"
        assert obj["test"] is True


class TestAttributeDelegation:
    """Fake stdout delegates attribute access to real stdout."""

    def test_encoding_attribute(self) -> None:
        original = sys.stdout
        init_io_guard()
        # encoding should be delegated to real stdout
        assert hasattr(sys.stdout, "encoding")
        if hasattr(original, "encoding"):
            assert sys.stdout.encoding == original.encoding

    def test_isatty_method(self) -> None:
        init_io_guard()
        # isatty should be delegated
        assert hasattr(sys.stdout, "isatty")
        # In test context, isatty() returns False
        assert sys.stdout.isatty() is False

    def test_buffer_attribute(self) -> None:
        """buffer attribute is delegated for binary write support."""
        init_io_guard()
        # Not all streams have .buffer (StringIO doesn't), but the delegation
        # mechanism should work without error.
        try:
            _ = sys.stdout.buffer
        except AttributeError:
            pass  # Expected if real stdout doesn't have buffer

    def test_reconfigure_method(self) -> None:
        """reconfigure() is delegated to the real stdout (important for prompt_test)."""
        real_out = io.StringIO()
        sys.stdout = real_out
        try:
            init_io_guard()
            # reconfigure should not raise, even if real stdout is StringIO
            # (StringIO may not have reconfigure, so catch AttributeError)
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except AttributeError:
                pass  # StringIO doesn't have reconfigure
        finally:
            teardown()


class TestClearCaptured:
    """clear_captured() empties both fake buffers."""

    def test_clear_stdout(self) -> None:
        init_io_guard()
        print("some output")
        assert "some output" in get_captured_stdout()
        clear_captured()
        assert get_captured_stdout() == ""

    def test_clear_stderr(self) -> None:
        init_io_guard()
        print("err", file=sys.stderr)
        assert "err" in get_captured_stderr()
        clear_captured()
        assert get_captured_stderr() == ""

    def test_clear_when_inactive(self) -> None:
        # Should not raise
        clear_captured()
