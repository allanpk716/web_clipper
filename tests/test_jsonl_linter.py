"""Tests for scripts/check_jsonl_purity.py — AST-based bare print() detector.

Covers:
- Current codebase passes (no violations)
- Synthetic code with print() is detected
- jsonl_emit() and other function calls are NOT flagged
- print() in comments is NOT flagged (ast naturally excludes)
- print() in docstrings is NOT flagged (ast naturally excludes)
- Multiline print() is detected
- builtins.print() is detected
- Exit codes: 0=clean, 1=violations
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# Import the linter under test
import sys

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_jsonl_purity import check_file, check_directory, main

# --- Fixtures ---


@pytest.fixture
def tmp_py_file(tmp_path: Path):
    """Return a factory that writes a temp .py file and returns its path."""

    def _write(source: str, name: str = "test_subject.py") -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(source), encoding="utf-8")
        return p

    return _write


# --- Core detection tests ---


class TestFileCheck:
    """Test check_file() on synthetic Python snippets."""

    def test_detects_bare_print(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('print("hello")\n')
        violations = check_file(p)
        assert len(violations) == 1
        line, col = violations[0]
        assert line == 1
        assert col == 0

    def test_detects_print_with_multiple_args(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('x = 1\nprint("value:", x)\n')
        violations = check_file(p)
        assert len(violations) == 1
        assert violations[0][0] == 2  # line 2

    def test_detects_multiline_print(self, tmp_py_file: Path) -> None:
        p = tmp_py_file(
            """\
            print(
                "hello",
                "world",
            )
            """
        )
        violations = check_file(p)
        assert len(violations) == 1

    def test_detects_builtins_print(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('builtins.print("via builtins")\n')
        violations = check_file(p)
        assert len(violations) == 1

    def test_detects_dunder_builtins_print(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('__builtins__.print("via dunder")\n')
        violations = check_file(p)
        assert len(violations) == 1

    def test_no_violation_for_jsonl_emit(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('jsonl_emit("progress", message="working")\n')
        violations = check_file(p)
        assert violations == []

    def test_no_violation_for_other_function_calls(self, tmp_py_file: Path) -> None:
        p = tmp_py_file(
            """\
            jsonl_emit_result(status="ok")
            jsonl_emit_error(stage="test", detail="fail")
            sys.stdout.write("hello")
            logger.info("info message")
            """
        )
        violations = check_file(p)
        assert violations == []

    def test_no_violation_for_print_in_comment(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('# print("this is a comment")\n')
        violations = check_file(p)
        assert violations == []

    def test_no_violation_for_print_in_docstring(self, tmp_py_file: Path) -> None:
        p = tmp_py_file(
            '''\
            def foo():
                """Use print("hello") for debugging."""
                pass
            '''
        )
        violations = check_file(p)
        assert violations == []

    def test_no_violation_for_print_in_string_literal(self, tmp_py_file: Path) -> None:
        p = tmp_py_file('msg = \'call print("hi") to output\'\n')
        violations = check_file(p)
        assert violations == []

    def test_no_violation_for_print_variable_name(self, tmp_py_file: Path) -> None:
        """A variable named 'print' is not a call — should not be flagged."""
        p = tmp_py_file("print = lambda x: None\n")
        violations = check_file(p)
        assert violations == []

    def test_multiple_prints_detected(self, tmp_py_file: Path) -> None:
        p = tmp_py_file(
            """\
            print("one")
            x = 2
            print("two")
            """
        )
        violations = check_file(p)
        assert len(violations) == 2

    def test_syntax_error_file_returns_empty(self, tmp_path: Path) -> None:
        """A file with syntax errors should not crash — just skip it."""
        p = tmp_path / "bad_syntax.py"
        p.write_text("def foo(:\n", encoding="utf-8")
        violations = check_file(p)
        assert violations == []

    def test_empty_file_is_clean(self, tmp_py_file: Path) -> None:
        p = tmp_py_file("")
        violations = check_file(p)
        assert violations == []


class TestDirectoryCheck:
    """Test check_directory() on temp directory trees."""

    def test_detects_violations_in_directory(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "dirty.py").write_text('print("oops")\n', encoding="utf-8")

        violations = check_directory(tmp_path)
        assert len(violations) == 1
        assert violations[0][0].name == "dirty.py"

    def test_clean_directory_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text("x = 1\njsonl_emit('ok')\n", encoding="utf-8")

        violations = check_directory(tmp_path)
        assert violations == []

    def test_nonexistent_directory_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as exc_info:
            check_directory(tmp_path / "nonexistent")
        assert exc_info.value.code == 2

    def test_scans_nested_directories(self, tmp_path: Path) -> None:
        sub = tmp_path / "subpkg"
        sub.mkdir()
        (sub / "nested.py").write_text('print("nested")\n', encoding="utf-8")

        violations = check_directory(tmp_path)
        assert len(violations) == 1
        assert "nested.py" in violations[0][0].as_posix()


class TestExitCodes:
    """Test main() exit codes."""

    def test_clean_codebase_exits_0(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
        assert main(["--directory", str(tmp_path)]) == 0

    def test_dirty_codebase_exits_1(self, tmp_path: Path) -> None:
        (tmp_path / "dirty.py").write_text('print("bad")\n', encoding="utf-8")
        assert main(["--directory", str(tmp_path)]) == 1

    def test_verbose_mode_exits_0(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
        assert main(["--directory", str(tmp_path), "--verbose"]) == 0


class TestCurrentCodebase:
    """Meta-test: verify the actual source tree has no bare print() calls."""

    def test_src_web_clip_helper_is_clean(self) -> None:
        """The production source under src/web_clip_helper/ must be print-free."""
        src_dir = Path(__file__).resolve().parent.parent / "src" / "web_clip_helper"
        if not src_dir.is_dir():
            pytest.skip("src/web_clip_helper not found — not running from project root")
        violations = check_directory(src_dir)
        assert violations == [], (
            f"Found {len(violations)} bare print() call(s) in production code:\n"
            + "\n".join(f"  {p}:{line}:{col}" for p, line, col in violations)
        )
