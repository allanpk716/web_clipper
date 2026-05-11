"""Tests that validate logging documentation against actual CLI behavior.

Reads README.md and AGENT_INSTRUCTION.md and verifies that the documented
log file path, format, fields, and redaction constraints are present and
consistent with the implementation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── Helpers ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_doc(name: str) -> str:
    """Return full text of a project documentation file."""
    path = PROJECT_ROOT / name
    if not path.exists():
        pytest.fail(f"Documentation file not found: {path}")
    return path.read_text(encoding="utf-8")


def _logging_section(text: str) -> str:
    """Extract the logging-related section from a document.

    Works for README.md (## 日志 header) and AGENT_INSTRUCTION.md
    (## 10. Structured Logs header).
    """
    # Try Chinese header first (README), then English (AGENT_INSTRUCTION)
    for pattern in [r"(##\s+日志.*)", r"(##\s+10\.\s+Structured Logs.*)"]:
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if m:
            # Return until the next ## header (or EOF)
            section = m.group(1)
            next_header = re.search(r"\n##\s+", section[10:])
            if next_header:
                return section[: next_header.start() + 10]
            return section
    return text  # fallback: search entire doc


# ── Log file path ──────────────────────────────────────────────────

class TestLogFilePath:
    """Both docs must mention the log file path."""

    @pytest.fixture(params=["README.md", "AGENT_INSTRUCTION.md"])
    def doc(self, request):
        return _read_doc(request.param)

    def test_contains_log_directory(self, doc):
        assert "~/.web-clip-helper/logs/" in doc or ".web-clip-helper/logs/" in doc, (
            "Log directory path not found in documentation"
        )

    def test_contains_log_filename(self, doc):
        assert "web-clip-helper.log" in doc, (
            "Log filename not found in documentation"
        )


# ── Log format ─────────────────────────────────────────────────────

class TestLogFormat:
    """Both docs must describe the structured log format."""

    @pytest.fixture(params=["README.md", "AGENT_INSTRUCTION.md"])
    def doc_section(self, request):
        return _logging_section(_read_doc(request.param))

    def test_mentions_timestamp_format(self, doc_section):
        assert re.search(r"YYYY-MM-DD|HH:MM:SS|timestamp", doc_section, re.IGNORECASE), (
            "Log timestamp format not documented"
        )

    def test_mentions_level(self, doc_section):
        assert re.search(r"\[LEVEL\]|\[INFO\]|\[ERROR\]|\[WARN", doc_section), (
            "Log level indicator not documented"
        )

    def test_mentions_key_value_pairs(self, doc_section):
        # Should show key=value pattern in examples
        assert re.search(r"\w+=\S+", doc_section), (
            "Key=value log format pattern not documented"
        )


# ── Key log fields ─────────────────────────────────────────────────

class TestLogFields:
    """Documentation must mention important pipeline stage fields."""

    @pytest.fixture(params=["README.md", "AGENT_INSTRUCTION.md"])
    def doc_section(self, request):
        return _logging_section(_read_doc(request.param))

    def test_mentions_elapsed_ms(self, doc_section):
        assert "elapsed_ms" in doc_section, (
            "elapsed_ms field not documented"
        )

    def test_mentions_stage(self, doc_section):
        # README uses Chinese 阶段; AGENT_INSTRUCTION uses "Stage"
        assert re.search(r"\bstage\b|阶段", doc_section, re.IGNORECASE), (
            "Pipeline stage not documented"
        )

    def test_mentions_content_length(self, doc_section):
        assert "content_length" in doc_section, (
            "content_length field not documented"
        )

    def test_mentions_image_count(self, doc_section):
        assert "image_count" in doc_section, (
            "image_count field not documented"
        )


# ── Redaction constraints ──────────────────────────────────────────

class TestRedactionConstraints:
    """AGENT_INSTRUCTION.md must explicitly document what is NOT logged."""

    def test_agent_instruction_mentions_redaction(self):
        doc = _read_doc("AGENT_INSTRUCTION.md")
        section = _logging_section(doc)
        # Should have a section about what is NOT logged
        assert re.search(r"not.*log|redaction|隐私|不会", section, re.IGNORECASE), (
            "Redaction/privacy constraints not documented in AGENT_INSTRUCTION.md"
        )

    def test_agent_instruction_lists_protected_fields(self):
        doc = _read_doc("AGENT_INSTRUCTION.md")
        section = _logging_section(doc)
        # Must mention at least content_length as metadata (not content)
        assert "content_length" in section, (
            "content_length not mentioned in logging section"
        )

    def test_agent_instruction_excludes_full_content(self):
        doc = _read_doc("AGENT_INSTRUCTION.md")
        section = _logging_section(doc)
        # Should explicitly say full content is NOT logged
        assert re.search(
            r"full\s+(markdown|content|text|article).*not|not.*full\s+(article|content|markdown|text)|不会.*完整|Do not.*expect.*full",
            section, re.IGNORECASE,
        ), (
            "Explicit exclusion of full content not documented"
        )


# ── No TBD/TODO in logging sections ────────────────────────────────

class TestNoPlaceholders:
    """Logging sections must not contain unfinished placeholders."""

    @pytest.fixture(params=["README.md", "AGENT_INSTRUCTION.md"])
    def doc_section(self, request):
        return _logging_section(_read_doc(request.param))

    def test_no_tbd(self, doc_section):
        assert "TBD" not in doc_section, (
            "Found 'TBD' placeholder in logging documentation"
        )

    def test_no_todo(self, doc_section):
        # Allow "TODO" in code blocks (e.g., example commands) but not in prose
        lines = [
            line for line in doc_section.splitlines()
            if not line.strip().startswith(("```", "    ", "#"))
        ]
        prose = "\n".join(lines)
        assert "TODO" not in prose, (
            "Found 'TODO' placeholder in logging documentation prose"
        )

    def test_no_placeholder_markers(self, doc_section):
        for marker in ["<TBD>", "<TODO>", "<PLACEHOLDER>", "xxx", "FIXME"]:
            assert marker not in doc_section, (
                f"Found '{marker}' placeholder in logging documentation"
            )
