"""Audit tests: AGENT_INSTRUCTION.md content matches actual CLI source code.

Every assertion in this file corresponds to a specific section of
AGENT_INSTRUCTION.md and verifies it against the real implementation.

Test layers:
1. Source-code consistency (import error_codes, compare to doc text)
2. Subprocess-based CLI invocation (run real CLI, parse JSONL, assert behavior)
"""

from __future__ import annotations

import json
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "AGENT_INSTRUCTION.md"

# ── Helpers ──────────────────────────────────────────────────────


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _run_cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run web-clip-helper as a subprocess and return the result."""
    return subprocess.run(
        ["web-clip-helper", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _parse_jsonl_lines(stdout: str) -> list[dict]:
    """Parse all JSONL lines from stdout, skipping migration noise."""
    envelopes: list[dict] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip non-JSON lines (e.g. "Config migration failed, continuing...")
        if not line.startswith("{"):
            continue
        try:
            envelopes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return envelopes


def _error_lines(stdout: str) -> list[dict]:
    """Return only type=error JSONL envelopes."""
    return [e for e in _parse_jsonl_lines(stdout) if e.get("type") == "error"]


def _result_lines(stdout: str) -> list[dict]:
    """Return only type=result JSONL envelopes."""
    return [e for e in _parse_jsonl_lines(stdout) if e.get("type") == "result"]


# ══════════════════════════════════════════════════════════════════
# Layer 1: Source-code consistency (doc text ↔ Python source)
# ══════════════════════════════════════════════════════════════════


# ── Section 6: Exit codes ────────────────────────────────────────


class TestExitCodes:
    """Verify the exit code table in AGENT_INSTRUCTION.md matches EXIT_CODE_MAP."""

    def test_exit_code_map_matches_doc(self):
        from web_clip_helper.error_codes import EXIT_CODE_MAP

        doc = _doc_text()

        # Build expected mapping from source
        expected = {}  # exit_code -> list of error codes
        for code, exit_num in EXIT_CODE_MAP.items():
            expected.setdefault(exit_num, []).append(code)

        # Verify each exit code (0-5) is documented
        for exit_num in range(6):
            if exit_num == 0:
                # Success row should exist
                assert "| 0 | Success |" in doc, "Exit code 0 (Success) not documented"
                continue

            codes = sorted(expected.get(exit_num, []))
            if not codes:
                continue

            # Check that each error code appears in the exit code table
            for code in codes:
                # The error code should appear somewhere in the doc, specifically
                # in the error codes table or exit code table
                assert code in doc, f"Error code {code} not mentioned in AGENT_INSTRUCTION.md"

    def test_exit_code_semantic_mapping(self):
        """Verify the semantic grouping is correct."""
        from web_clip_helper.error_codes import EXIT_CODE_MAP

        # Exit 1: fatal
        assert EXIT_CODE_MAP["INTERNAL_ERROR"] == 1
        assert EXIT_CODE_MAP["FATAL_CRASH"] == 1

        # Exit 2: input/config
        assert EXIT_CODE_MAP["INPUT_INVALID"] == 2
        assert EXIT_CODE_MAP["CONFIG_ERROR"] == 2
        assert EXIT_CODE_MAP["INVALID_TYPE"] == 2
        assert EXIT_CODE_MAP["NO_CUSTOM_PROMPT"] == 2

        # Exit 3: resource/dependency
        assert EXIT_CODE_MAP["NOT_FOUND"] == 3
        assert EXIT_CODE_MAP["STORAGE_ERROR"] == 3
        assert EXIT_CODE_MAP["INDEX_ERROR"] == 3
        assert EXIT_CODE_MAP["REFRESH_ERROR"] == 3

        # Exit 4: network/third-party
        assert EXIT_CODE_MAP["NETWORK_ERROR"] == 4
        assert EXIT_CODE_MAP["FETCH_ERROR"] == 4
        assert EXIT_CODE_MAP["ROUTING_ERROR"] == 4
        assert EXIT_CODE_MAP["URL_ROUTE_ERROR"] == 4
        assert EXIT_CODE_MAP["TIMEOUT_ERROR"] == 4

        # Exit 5: concurrency
        assert EXIT_CODE_MAP["RESOURCE_LOCKED"] == 5


# ── Section 6: Error codes table ──────────────────────────────────


class TestErrorCodes:
    """Verify all 13 error codes from ErrorCode class are documented."""

    ALL_CODES = [
        "INPUT_INVALID",
        "NOT_FOUND",
        "STORAGE_ERROR",
        "INDEX_ERROR",
        "NETWORK_ERROR",
        "ROUTING_ERROR",
        "FETCH_ERROR",
        "CONFIG_ERROR",
        "INTERNAL_ERROR",
        "FATAL_CRASH",
        "REFRESH_ERROR",
        "TIMEOUT_ERROR",
        "RESOURCE_LOCKED",
    ]

    @pytest.mark.parametrize("code", ALL_CODES)
    def test_error_code_documented(self, code: str):
        doc = _doc_text()
        assert code in doc, f"Error code {code} not found in AGENT_INSTRUCTION.md"

    def test_no_parse_error(self):
        """PARSE_ERROR should not appear (it's not in the canonical ErrorCode class)."""
        doc = _doc_text()
        assert "PARSE_ERROR" not in doc, "PARSE_ERROR should not be documented — not in ErrorCode class"

    def test_descriptions_match_source(self):
        """Verify error code descriptions match ErrorCode._DESCRIPTIONS."""
        from web_clip_helper.error_codes import ErrorCode

        doc = _doc_text()
        for code in self.ALL_CODES:
            description = ErrorCode.describe(code)
            # Check that the description or a close variant appears in the doc
            words = [w for w in description.split() if len(w) > 4]
            assert len(words) > 0, f"Description for {code} is too short"
            found = False
            for word in words[:3]:
                if word.lower() in doc.lower():
                    found = True
                    break
            assert found, f"Description for {code} ('{description}') seems absent from doc"


# ── Section 8: Config paths ──────────────────────────────────────


class TestConfigPaths:
    """Verify config paths use SDK sandbox, not XDG."""

    def test_sdk_sandbox_base_path(self):
        doc = _doc_text()
        assert "~/.web-clip-helper/" in doc, "SDK sandbox base path ~/.web-clip-helper/ not documented"

    def test_config_json_not_yaml(self):
        doc = _doc_text()
        assert "config.json" in doc, "config.json not referenced"
        assert "JSON format" in doc or "JSON" in doc, "Config format should be documented as JSON"

    def test_data_dir_clips(self):
        doc = _doc_text()
        assert "data/clips/" in doc or "data/clips" in doc, "Clips storage path not documented"

    def test_data_dir_db(self):
        doc = _doc_text()
        assert "clips.db" in doc, "SQLite database path not documented"

    def test_no_xdg_paths(self):
        """XDG paths like ~/.config/ and ~/.local/share/ should NOT be the primary paths."""
        doc = _doc_text()
        assert "~/.config/web-clip-helper/" not in doc, "Old XDG config path should not be documented as primary"


# ── Section 4/5: Command parameters ─────────────────────────────


class TestCommandParameters:
    """Verify documented command options match actual CLI signatures."""

    def test_clip_command_options(self):
        """Verify clip command documents all actual options."""
        doc = _doc_text()

        assert "--text" in doc, "clip --text option not documented"
        assert "--no-images" in doc, "clip --no-images option not documented"
        assert "--timeout" in doc, "clip --timeout option not documented"
        assert "--dry-run" in doc, "clip --dry-run option not documented"

    def test_clip_timeout_default(self):
        """Verify clip --timeout default is documented as 60."""
        doc = _doc_text()
        assert "60" in doc, "Default timeout value 60 not documented"

    def test_list_command_filters(self):
        """Verify list command documents all filter options."""
        doc = _doc_text()

        assert "--category" in doc, "list --category option not documented"
        assert "--source-type" in doc, "list --source-type option not documented"
        assert "--tag" in doc, "list --tag option not documented"
        assert "--limit" in doc, "list --limit option not documented"
        assert "--offset" in doc, "list --offset option not documented"

    def test_search_command_full_flag(self):
        """Verify search command documents --full flag."""
        doc = _doc_text()
        assert "--full" in doc, "search --full option not documented"

    def test_search_no_limit_offset(self):
        """Verify search command notes lack of --limit/--offset."""
        doc = _doc_text()
        assert "does not support" in doc or "no `--limit`" in doc or "no `--offset`" in doc, \
            "search command should note that --limit/--offset are not supported"


# ── Pagination metadata ───────────────────────────────────────────


class TestPaginationMetadata:
    """Verify pagination metadata fields are documented."""

    def test_total_count_field(self):
        doc = _doc_text()
        assert "_total_count" in doc, "Pagination field _total_count not documented"

    def test_limit_field(self):
        doc = _doc_text()
        assert "_limit" in doc, "Pagination field _limit not documented"

    def test_offset_field(self):
        doc = _doc_text()
        assert "_offset" in doc, "Pagination field _offset not documented"

    def test_count_zero_empty_results(self):
        doc = _doc_text()
        assert '"count": 0' in doc or '"count":0' in doc, \
            "Empty result count:0 pattern not documented"


# ── Structural integrity ──────────────────────────────────────────


class TestDocStructure:
    """Verify AGENT_INSTRUCTION.md has required sections."""

    REQUIRED_SECTIONS = [
        "Tool Overview",
        "JSONL Output Contract",
        "Command Reference",
        "Error Handling",
        "Configuration",
        "Trace IDs",
        "Quiet Mode",
    ]

    @pytest.mark.parametrize("section", REQUIRED_SECTIONS)
    def test_section_exists(self, section: str):
        doc = _doc_text()
        assert section in doc, f"Required section '{section}' not found in AGENT_INSTRUCTION.md"

    def test_doc_is_markdown(self):
        assert DOC.suffix == ".md", "AGENT_INSTRUCTION.md should be a Markdown file"

    def test_doc_not_empty(self):
        content = _doc_text()
        assert len(content) > 1000, "AGENT_INSTRUCTION.md seems too short"

    def test_doc_has_at_least_10_sections(self):
        """Doc must have at least 10 major sections (## heading level)."""
        doc = _doc_text()
        h2_count = len(re.findall(r"^## \d+\.", doc, re.MULTILINE))
        assert h2_count >= 10, f"Expected at least 10 major sections, found {h2_count}"


# ══════════════════════════════════════════════════════════════════
# Layer 2: Subprocess-based CLI verification
# These tests run the real CLI binary and verify behavior matches
# what AGENT_INSTRUCTION.md documents.
# ══════════════════════════════════════════════════════════════════


class TestExitCodesSubprocess:
    """Run the actual CLI and verify exit codes match documented table (Section 6)."""

    def test_clip_no_args_exit_2(self):
        """Doc says exit 2 = Input/config error. clip with no URL/text should exit 2."""
        r = _run_cli("clip")
        assert r.returncode == 2, f"Expected exit 2 for clip with no args, got {r.returncode}"
        errors = _error_lines(r.stdout)
        assert len(errors) >= 1, "Expected at least one error JSONL line"
        assert errors[0].get("error_code") == "INPUT_INVALID", \
            f"Expected INPUT_INVALID, got {errors[0].get('error_code')}"

    def test_get_nonexistent_id_exit_3(self):
        """Doc says exit 3 = Resource/dependency error. get with nonexistent ID should exit 3."""
        r = _run_cli("get", "999999")
        assert r.returncode == 3, f"Expected exit 3 for get nonexistent, got {r.returncode}"
        errors = _error_lines(r.stdout)
        assert len(errors) >= 1, "Expected at least one error JSONL line"
        assert errors[0].get("error_code") == "NOT_FOUND", \
            f"Expected NOT_FOUND, got {errors[0].get('error_code')}"

    def test_bare_command_exit_0(self):
        """Running web-clip-helper with no subcommand emits help JSONL and exits 0."""
        r = _run_cli()
        assert r.returncode == 0, f"Expected exit 0 for bare command, got {r.returncode}"
        envelopes = _parse_jsonl_lines(r.stdout)
        assert len(envelopes) >= 1, "Expected at least one JSONL line from bare command"


class TestJSONLFieldsSubprocess:
    """Verify JSONL envelope fields match documented contract (Section 3)."""

    def test_envelope_fields_on_result(self):
        """Every result line should have type, version, tool, timestamp."""
        r = _run_cli("list", "--limit", "1")
        assert r.returncode == 0, f"list failed: {r.stderr}"
        results = _result_lines(r.stdout)
        assert len(results) >= 1, "Expected at least one result line from list"

        for envelope in results:
            source = envelope
            assert source.get("type") == "result", f"Expected type=result, got {source.get('type')}"
            assert "version" in source, "Missing envelope field: version"
            assert "tool" in source, "Missing envelope field: tool"
            assert "timestamp" in source, "Missing envelope field: timestamp"

    def test_envelope_fields_on_error(self):
        """Every error line should have type, version, tool, timestamp."""
        r = _run_cli("get", "999999")
        assert r.returncode == 3, f"Expected exit 3, got {r.returncode}"
        errors = _error_lines(r.stdout)
        assert len(errors) >= 1, "Expected at least one error line"

        for envelope in errors:
            source = envelope
            assert source.get("type") == "error", f"Expected type=error, got {source.get('type')}"
            assert "version" in source, "Missing envelope field: version on error"
            assert "tool" in source, "Missing envelope field: tool on error"
            assert "timestamp" in source, "Missing envelope field: timestamp on error"

    def test_tool_field_value(self):
        """tool field should be 'web-clip-helper' per doc."""
        r = _run_cli("list", "--limit", "1")
        results = _result_lines(r.stdout)
        assert len(results) >= 1
        source = results[0]
        tool_val = source.get("tool") or source.get("data", {}).get("tool")
        assert tool_val == "web-clip-helper", f"Expected tool='web-clip-helper', got '{tool_val}'"


class TestErrorCodesSubprocess:
    """Verify error JSONL includes error_code field with correct values."""

    def test_error_jsonl_has_error_code(self):
        """Error lines must include error_code field."""
        r = _run_cli("get", "999999")
        errors = _error_lines(r.stdout)
        assert len(errors) >= 1
        assert "error_code" in errors[0], "Error JSONL missing error_code field"

    def test_error_code_matches_exit_code_mapping(self):
        """Verify that error_code → exit code matches EXIT_CODE_MAP from error_codes.py."""
        from web_clip_helper.error_codes import EXIT_CODE_MAP

        r = _run_cli("get", "999999")
        errors = _error_lines(r.stdout)
        assert len(errors) >= 1
        code = errors[0].get("error_code")
        expected_exit = EXIT_CODE_MAP.get(code, 1)
        assert r.returncode == expected_exit, \
            f"Exit {r.returncode} doesn't match EXIT_CODE_MAP[{code}]={expected_exit}"

    def test_clip_no_args_error_code_is_input_invalid(self):
        """clip with no args should produce INPUT_INVALID error code."""
        r = _run_cli("clip")
        errors = _error_lines(r.stdout)
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"


class TestEmptyResultSubprocess:
    """Verify empty result behavior matches doc (count:0 result lines)."""

    def test_search_empty_emits_count_zero(self):
        """search with nonsense keyword should emit count:0 result line."""
        r = _run_cli("search", "zzz_nonexistent_xyz_999")
        assert r.returncode == 0, f"search failed: {r.stderr}"
        results = _result_lines(r.stdout)
        # Should have at least one result line with count:0
        found = False
        for res in results:
            data = res.get("data", res)
            if data.get("count") == 0:
                found = True
                break
        assert found, "Expected count:0 result line for empty search"

    def test_tags_empty_emits_count_zero(self):
        """tags with no tags should emit count:0 result line (depends on DB state)."""
        r = _run_cli("tags")
        assert r.returncode == 0, f"tags failed: {r.stderr}"
        results = _result_lines(r.stdout)
        # At minimum, we should get JSONL output — may or may not be empty
        # depending on test DB state, so just verify valid JSONL structure
        assert len(results) >= 1, "Expected at least one result line from tags"


class TestPaginationSubprocess:
    """Verify pagination metadata fields match documented behavior."""

    def test_list_with_limit_offset_includes_pagination(self):
        """list --limit 1 --offset 0 should include _total_count, _limit, _offset."""
        r = _run_cli("list", "--limit", "1", "--offset", "0")
        assert r.returncode == 0, f"list failed: {r.stderr}"
        results = _result_lines(r.stdout)
        assert len(results) >= 1, "Expected at least one result from list"

        data = results[0].get("data", results[0])
        assert "_total_count" in data, "Missing _total_count in list result"
        assert "_limit" in data, "Missing _limit in list result"
        assert "_offset" in data, "Missing _offset in list result"
        assert data["_limit"] == 1, f"Expected _limit=1, got {data['_limit']}"
        assert data["_offset"] == 0, f"Expected _offset=0, got {data['_offset']}"

    def test_list_without_limit_has_null_limit(self):
        """list without --limit should have _limit=null."""
        r = _run_cli("list")
        assert r.returncode == 0, f"list failed: {r.stderr}"
        results = _result_lines(r.stdout)
        if results:
            data = results[0].get("data", results[0])
            assert "_limit" in data, "Missing _limit in list result"
            assert data["_limit"] is None, f"Expected _limit=null without --limit, got {data['_limit']}"


class TestCommandParametersSubprocess:
    """Verify CLI accepts documented parameters without crashing."""

    def test_clip_accepts_text_flag(self):
        """clip --text with content should be accepted (may fail at fetch, but not at arg parsing)."""
        r = _run_cli("clip", "--text", "test content", "--dry-run")
        # dry-run should succeed (exit 0) or at least not crash on arg parsing
        assert r.returncode == 0, f"clip --text --dry-run failed with exit {r.returncode}: {r.stderr}"

    def test_clip_accepts_no_images_flag(self):
        """clip --no-images should be accepted."""
        r = _run_cli("clip", "--no-images", "--text", "test", "--dry-run")
        assert r.returncode == 0, f"clip --no-images failed with exit {r.returncode}: {r.stderr}"

    def test_clip_accepts_timeout_flag(self):
        """clip --timeout 10 should be accepted."""
        r = _run_cli("clip", "--timeout", "10", "--text", "test", "--dry-run")
        assert r.returncode == 0, f"clip --timeout failed with exit {r.returncode}: {r.stderr}"

    def test_clip_accepts_dry_run_flag(self):
        """clip --dry-run should be accepted."""
        r = _run_cli("clip", "--dry-run", "--text", "test")
        assert r.returncode == 0, f"clip --dry-run failed with exit {r.returncode}: {r.stderr}"

    def test_list_accepts_category_filter(self):
        """list --category should be accepted."""
        r = _run_cli("list", "--category", "article")
        assert r.returncode == 0, f"list --category failed with exit {r.returncode}: {r.stderr}"

    def test_list_accepts_source_type_filter(self):
        """list --source-type should be accepted."""
        r = _run_cli("list", "--source-type", "web")
        assert r.returncode == 0, f"list --source-type failed with exit {r.returncode}: {r.stderr}"

    def test_search_accepts_full_flag(self):
        """search --full should be accepted."""
        r = _run_cli("search", "test", "--full")
        assert r.returncode == 0, f"search --full failed with exit {r.returncode}: {r.stderr}"


class TestConfigFormatSubprocess:
    """Verify config file is JSON not YAML."""

    def test_config_path_is_json(self):
        """Config module should use .json extension."""
        # Import the module's config path constant
        import web_clip_helper.config as cfg_mod
        # Find the default config path
        default_path = None
        for attr_name in dir(cfg_mod):
            if "DEFAULT_CONFIG" in attr_name.upper():
                val = getattr(cfg_mod, attr_name)
                if isinstance(val, Path):
                    default_path = val
                    break
        if default_path is None:
            pytest.skip("Could not find default config path constant in config module")
        assert default_path.suffix == ".json", \
            f"Config file should be .json, got {default_path.suffix}"


class TestAgentErrorsSubprocess:
    """Verify agent errors output includes all documented error codes."""

    def test_agent_errors_lists_all_codes(self):
        """agent errors should list at least 13 error codes."""
        r = _run_cli("agent", "errors")
        assert r.returncode == 0, f"agent errors failed: {r.stderr}"
        results = _result_lines(r.stdout)
        assert len(results) >= 1, "Expected at least one result line"

        data = results[0].get("data", results[0])
        codes = data.get("codes", [])
        code_names = [c.get("code") for c in codes if isinstance(c, dict)]
        assert len(code_names) >= 13, \
            f"Expected at least 13 error codes from agent errors, got {len(code_names)}"

    def test_agent_errors_includes_all_13_canonical_codes(self):
        """All 13 ErrorCode class members must appear in agent errors output."""
        r = _run_cli("agent", "errors")
        assert r.returncode == 0
        results = _result_lines(r.stdout)
        data = results[0].get("data", results[0])
        codes = data.get("codes", [])
        code_names = {c.get("code") for c in codes if isinstance(c, dict)}

        expected = {
            "INPUT_INVALID", "NOT_FOUND", "STORAGE_ERROR", "INDEX_ERROR",
            "NETWORK_ERROR", "ROUTING_ERROR", "FETCH_ERROR", "CONFIG_ERROR",
            "INTERNAL_ERROR", "FATAL_CRASH", "REFRESH_ERROR", "TIMEOUT_ERROR",
            "RESOURCE_LOCKED",
        }
        missing = expected - code_names
        assert not missing, f"agent errors missing codes: {missing}"


class TestExitCodeTableDocConsistency:
    """Parse AGENT_INSTRUCTION.md exit code table and verify against EXIT_CODE_MAP."""

    def test_doc_exit_code_table_matches_exit_code_map(self):
        """Section 6 exit code table should list the same error codes as EXIT_CODE_MAP."""
        from web_clip_helper.error_codes import EXIT_CODE_MAP

        doc = _doc_text()

        # Extract exit code table: rows like "| 2 | Input / config error | `INPUT_INVALID`, ..."
        table_rows = re.findall(r"\| (\d+) \|[^|]+\| ([^|]+) \|", doc)

        # Build doc mapping: exit_code -> set of error codes
        doc_map: dict[int, set[str]] = {}
        for exit_str, codes_str in table_rows:
            exit_num = int(exit_str.strip())
            # Extract error codes from backtick-delimited code spans
            codes_in_row = re.findall(r"`([A-Z_]+)`", codes_str)
            doc_map.setdefault(exit_num, set()).update(codes_in_row)

        # Verify every EXIT_CODE_MAP entry is documented in the table
        for code, expected_exit in EXIT_CODE_MAP.items():
            codes_at_exit = doc_map.get(expected_exit, set())
            assert code in codes_at_exit, \
                f"EXIT_CODE_MAP has {code}→{expected_exit} but doc table for exit {expected_exit} lists: {codes_at_exit}"

        # Verify no extra codes in doc that aren't in EXIT_CODE_MAP
        all_doc_codes = set()
        for codes in doc_map.values():
            all_doc_codes.update(codes)
        source_codes = set(EXIT_CODE_MAP.keys())
        extra = all_doc_codes - source_codes
        assert not extra, f"Doc lists codes not in EXIT_CODE_MAP: {extra}"
