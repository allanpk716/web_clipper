#!/usr/bin/env python
"""AST-based linter that detects bare print() calls in production source code.

Ensures all output goes through the JSONL emitter functions (jsonl_emit, etc.)
rather than raw print(). This enforces the "absolutely structured communication"
requirement at the CI level.

Exit codes:
    0 — no violations found (clean)
    1 — one or more bare print() calls detected
    2 — usage / argument error

Usage:
    python scripts/check_jsonl_purity.py
    python scripts/check_jsonl_purity.py --directory src/web_clip_helper
    python scripts/check_jsonl_purity.py --verbose
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Default directory to scan
DEFAULT_DIR = "src/web_clip_helper"


def check_file(filepath: Path) -> list[tuple[int, int]]:
    """Parse a single Python file and return (line, col) for each bare print() call.

    Uses the ast module so comments, docstrings, and string literals are
    naturally excluded — the parser never sees them.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"WARNING: cannot read {filepath}: {exc}", file=sys.stderr)
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        print(f"WARNING: cannot parse {filepath}: {exc}", file=sys.stderr)
        return []

    violations: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Bare print(...) — func is ast.Name with id "print"
        if isinstance(func, ast.Name) and func.id == "print":
            violations.append((node.lineno, node.col_offset))
        # builtins.print(...) or __builtins__.print(...)
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "print"
            and isinstance(func.value, ast.Name)
            and func.value.id in ("builtins", "__builtins__")
        ):
            violations.append((node.lineno, node.col_offset))

    return violations


def check_directory(directory: Path, *, verbose: bool = False) -> list[tuple[Path, int, int]]:
    """Scan all .py files under *directory* and return violations.

    Returns a list of (filepath, line, col) tuples.
    """
    if not directory.is_dir():
        print(f"ERROR: {directory} is not a directory", file=sys.stderr)
        sys.exit(2)

    all_violations: list[tuple[Path, int, int]] = []
    py_files = sorted(directory.rglob("*.py"))

    if verbose:
        print(f"Scanning {len(py_files)} Python files in {directory} ...")

    for filepath in py_files:
        violations = check_file(filepath)
        for line, col in violations:
            all_violations.append((filepath, line, col))

    return all_violations


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code (0=clean, 1=violations)."""
    parser = argparse.ArgumentParser(
        description="Detect bare print() calls in production source code.",
    )
    parser.add_argument(
        "--directory",
        default=DEFAULT_DIR,
        help=f"Directory to scan (default: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed output including files scanned",
    )
    args = parser.parse_args(argv)

    directory = Path(args.directory)
    violations = check_directory(directory, verbose=args.verbose)

    if violations:
        for filepath, line, col in violations:
            # Use forward slashes for consistency across platforms
            rel = filepath.as_posix()
            print(f"{rel}:{line}:{col}: bare print() call found")
        if args.verbose:
            print(f"\n{len(violations)} violation(s) found.")
        return 1

    if args.verbose:
        print("No bare print() calls found. Clean!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
