"""Tests for the Arxiv adapter — URL pattern, paper ID extraction, metadata parsing, PDF download, Chinese summary."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.arxiv import (
    ArxivAdapter,
    _extract_paper_id,
    _parse_metadata,
    _sanitize_filename,
    _URL_PATTERN,
)
from web_clip_helper.models import RawContent

# ── Sample HTML ──────────────────────────────────────────────────────

SAMPLE_ABS_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta name="citation_title" content="Formal Analysis and Supply Chain Security for Agentic AI Skills">
<meta name="citation_author" content="Bhardwaj, Varun Pratap">
<meta name="citation_author" content="Smith, Jane">
<meta name="citation_date" content="2026/02/27">
<meta name="citation_online_date" content="2026/02/27">
<meta name="citation_arxiv_category" content="cs.CR">
<meta name="citation_arxiv_category" content="cs.AI">
</head>
<body>
<div id="content-inner">
<div class="list-title mathjax">
<span class="descriptor">Title:</span>
Formal Analysis and Supply Chain Security for Agentic AI Skills
</div>
<div class="list-authors">
<span class="descriptor">Authors:</span>
<a href="#">Varun Pratap Bhardwaj</a>, <a href="#">Jane Smith</a>
</div>
<blockquote class="abstract mathjax">
<span class="descriptor">Abstract:</span>
The rapid proliferation of agentic AI skill ecosystems has introduced a critical supply chain attack surface.
This paper presents a formal analysis framework.
</blockquote>
<div class="subjects">
<span class="primary-subject">Cryptography and Security (cs.CR)</span>
</div>
</div>
</body>
</html>
"""

SAMPLE_ABS_HTML_MINIMAL = """\
<!DOCTYPE html>
<html>
<head>
<meta name="citation_title" content="Minimal Paper">
</head>
<body>
<blockquote class="abstract mathjax">
<span class="descriptor">Abstract:</span>
A minimal abstract.
</blockquote>
</body>
</html>
"""


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_router():
    """Preserve/restore global router state."""
    saved = adapter_router.copy()
    adapter_router.clear()
    yield
    adapter_router.clear()
    adapter_router.extend(saved)


def _mock_response(
    status_code: int = 200,
    text: str = "",
    content: bytes = b"",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    resp.headers = headers or {"content-type": "application/pdf"}

    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{status_code}",
                request=MagicMock(),
                response=resp,
            )

    resp.raise_for_status = raise_for_status
    return resp


# ── Paper ID extraction ─────────────────────────────────────────────


class TestExtractPaperId:
    def test_abs_url(self):
        assert _extract_paper_id("https://arxiv.org/abs/2603.00195") == "2603.00195"

    def test_pdf_url(self):
        assert _extract_paper_id("https://arxiv.org/pdf/2603.00195") == "2603.00195"

    def test_versioned_url(self):
        assert _extract_paper_id("https://arxiv.org/abs/2603.00195v1") == "2603.00195v1"

    def test_versioned_pdf_url(self):
        assert _extract_paper_id("https://arxiv.org/pdf/2603.00195v2") == "2603.00195v2"

    def test_longer_id(self):
        assert _extract_paper_id("https://arxiv.org/abs/2301.01234") == "2301.01234"

    def test_http_url(self):
        assert _extract_paper_id("http://arxiv.org/abs/2603.00195") == "2603.00195"

    def test_url_with_query(self):
        assert (
            _extract_paper_id("https://arxiv.org/abs/2603.00195?foo=bar")
            == "2603.00195"
        )

    def test_invalid_url_raises(self):
        with pytest.raises(AdapterError, match="Cannot extract"):
            _extract_paper_id("https://example.com/paper/123")


# ── Metadata parsing ────────────────────────────────────────────────


class TestParseMetadata:
    def test_full_metadata(self):
        result = _parse_metadata(SAMPLE_ABS_HTML)
        assert result["title"] == "Formal Analysis and Supply Chain Security for Agentic AI Skills"
        assert result["authors"] == ["Bhardwaj, Varun Pratap", "Smith, Jane"]
        assert "agentic AI" in result["abstract"]
        assert "Cryptography and Security (cs.CR)" in result["categories"]
        assert result["date"] == "2026/02/27"

    def test_minimal_html(self):
        result = _parse_metadata(SAMPLE_ABS_HTML_MINIMAL)
        assert result["title"] == "Minimal Paper"
        assert result["authors"] == []
        assert "minimal abstract" in result["abstract"].lower()
        assert result["categories"] == []
        assert result["date"] == ""

    def test_empty_html(self):
        result = _parse_metadata("<html><body></body></html>")
        assert result["title"] == "Untitled"
        assert result["authors"] == []
        assert result["abstract"] == ""
        assert result["categories"] == []

    def test_abstract_html_tags_stripped(self):
        html = """\
        <blockquote class="abstract mathjax">
        <span class="descriptor">Abstract:</span>
        Text with <b>bold</b> and <i>italic</i> tags.
        </blockquote>
        """
        result = _parse_metadata(html)
        assert "<b>" not in result["abstract"]
        assert "bold" in result["abstract"]
        assert "italic" in result["abstract"]


# ── Filename sanitization ───────────────────────────────────────────


class TestSanitizeFilename:
    def test_simple_title(self):
        assert _sanitize_filename("My Paper Title") == "My Paper Title"

    def test_special_chars(self):
        result = _sanitize_filename('What is "AI"?')
        assert '"' not in result
        assert "AI" in result

    def test_colons_and_slashes(self):
        result = _sanitize_filename("Title: A/B|C")
        assert ":" not in result
        assert "/" not in result

    def test_preserves_chinese(self):
        assert "中文" in _sanitize_filename("中文论文标题")

    def test_empty_returns_untitled(self):
        assert _sanitize_filename("") == "untitled"

    def test_truncates_long_title(self):
        result = _sanitize_filename("A" * 300)
        assert len(result) <= 200


# ── URL routing ─────────────────────────────────────────────────────


class TestArxivRouting:
    def test_abs_url_routes_to_arxiv(self):
        from web_clip_helper.adapter import register_adapter
        register_adapter(_URL_PATTERN, ArxivAdapter)
        cls = route_url("https://arxiv.org/abs/2603.00195")
        assert cls is ArxivAdapter

    def test_pdf_url_routes_to_arxiv(self):
        from web_clip_helper.adapter import register_adapter
        register_adapter(_URL_PATTERN, ArxivAdapter)
        cls = route_url("https://arxiv.org/pdf/2603.00195")
        assert cls is ArxivAdapter

    def test_http_url_routes_to_arxiv(self):
        from web_clip_helper.adapter import register_adapter
        register_adapter(_URL_PATTERN, ArxivAdapter)
        cls = route_url("http://arxiv.org/abs/2603.00195")
        assert cls is ArxivAdapter


# ── source_type ─────────────────────────────────────────────────────


class TestSourceType:
    def test_source_type_is_arxiv(self):
        assert ArxivAdapter.source_type == "arxiv"


# ── Full fetch (mocked HTTP) ────────────────────────────────────────


class TestArxivAdapterFetch:
    @patch("web_clip_helper.adapters.arxiv._generate_chinese_summary", return_value="这是中文概括")
    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_success(self, mock_client_cls, mock_summary):
        # Setup mock client
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        # First call: abs page, Second call: PDF
        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        pdf_resp = _mock_response(
            content=b"%PDF-1.4 fake pdf content",
            headers={"content-type": "application/pdf"},
        )
        mock_client.get.side_effect = [abs_resp, pdf_resp]

        adapter = ArxivAdapter()
        result = adapter.fetch("https://arxiv.org/abs/2603.00195")

        assert isinstance(result, RawContent)
        assert result.source_type == "arxiv"
        assert result.url == "https://arxiv.org/abs/2603.00195"
        assert "Supply Chain Security" in result.title
        assert "这是中文概括" in result.content_md
        assert "Abstract" in result.content_md
        assert "agentic AI" in result.content_md
        assert result.images == []
        assert len(result.extra_files) == 1
        # PDF filename should end with .pdf
        pdf_name = list(result.extra_files.keys())[0]
        assert pdf_name.endswith(".pdf")
        assert result.extra_files[pdf_name] == b"%PDF-1.4 fake pdf content"

    @patch("web_clip_helper.adapters.arxiv._generate_chinese_summary", return_value="")
    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_without_chinese_summary(self, mock_client_cls, mock_summary):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        pdf_resp = _mock_response(
            content=b"%PDF-1.4 fake pdf content",
            headers={"content-type": "application/pdf"},
        )
        mock_client.get.side_effect = [abs_resp, pdf_resp]

        adapter = ArxivAdapter()
        result = adapter.fetch("https://arxiv.org/abs/2603.00195")

        # Should NOT have Chinese summary section
        assert "摘要" not in result.content_md
        # But should still have abstract
        assert "Abstract" in result.content_md
        assert "agentic AI" in result.content_md

    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_abs_page_http_error_raises(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = _mock_response(status_code=404)
        mock_client.get.return_value = resp

        adapter = ArxivAdapter()
        with pytest.raises(AdapterError, match="HTTP 404"):
            adapter.fetch("https://arxiv.org/abs/9999.99999")

    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_pdf_http_error_raises(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        # First call (abs page) succeeds, second (PDF) fails
        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        pdf_resp = _mock_response(status_code=503)

        mock_client.get.side_effect = [abs_resp, pdf_resp]

        adapter = ArxivAdapter()
        with pytest.raises(AdapterError, match="HTTP 503"):
            adapter.fetch("https://arxiv.org/abs/2603.00195")

    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_pdf_timeout_raises(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        mock_client.get.side_effect = [abs_resp, httpx.TimeoutException("timeout")]

        adapter = ArxivAdapter()
        with pytest.raises(AdapterError, match="[Tt]imeout"):
            adapter.fetch("https://arxiv.org/abs/2603.00195")

    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_pdf_non_pdf_content_raises(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        pdf_resp = _mock_response(
            content=b"<html>Error</html>",
            headers={"content-type": "text/html"},
        )

        mock_client.get.side_effect = [abs_resp, pdf_resp]

        adapter = ArxivAdapter()
        with pytest.raises(AdapterError, match="non-PDF"):
            adapter.fetch("https://arxiv.org/abs/2603.00195")

    @patch("web_clip_helper.adapters.arxiv._generate_chinese_summary", return_value="概括")
    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_fetch_pdf_url_extracts_id_and_works(self, mock_client_cls, mock_summary):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        pdf_resp = _mock_response(
            content=b"%PDF-1.4 content",
            headers={"content-type": "application/pdf"},
        )
        mock_client.get.side_effect = [abs_resp, pdf_resp]

        adapter = ArxivAdapter()
        result = adapter.fetch("https://arxiv.org/pdf/2603.00195")

        assert result.source_type == "arxiv"
        assert len(result.extra_files) == 1

    @patch("web_clip_helper.adapters.arxiv._generate_chinese_summary", return_value="概括")
    @patch("web_clip_helper.adapters.arxiv.httpx.Client")
    def test_content_md_has_metadata_header(self, mock_client_cls, mock_summary):
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        abs_resp = _mock_response(text=SAMPLE_ABS_HTML)
        pdf_resp = _mock_response(
            content=b"%PDF-1.4 content",
            headers={"content-type": "application/pdf"},
        )
        mock_client.get.side_effect = [abs_resp, pdf_resp]

        adapter = ArxivAdapter()
        result = adapter.fetch("https://arxiv.org/abs/2603.00195")

        assert "> Source:" in result.content_md
        assert "> Clipped:" in result.content_md
        assert "> Authors:" in result.content_md
        assert "> Submitted:" in result.content_md
        assert "> Categories:" in result.content_md


# ── Chinese summary generation (non-fatal) ──────────────────────────


class TestChineseSummaryNonFatal:
    @patch("web_clip_helper.adapters.arxiv.get_config")
    def test_no_api_key_returns_empty(self, mock_config):
        mock_config.return_value.llm.api_key = ""
        from web_clip_helper.adapters.arxiv import _generate_chinese_summary

        result = _generate_chinese_summary("some abstract", "some title")
        assert result == ""

    @patch("web_clip_helper.adapters.arxiv.get_config")
    def test_empty_abstract_returns_empty(self, mock_config):
        mock_config.return_value.llm.api_key = "test-key"
        from web_clip_helper.adapters.arxiv import _generate_chinese_summary

        result = _generate_chinese_summary("", "some title")
        assert result == ""


# ── Integration: source_type attribute ──────────────────────────────


class TestIntegration:
    def test_arxiv_source_type(self):
        """Verify source_type is set correctly for downstream routing."""
        assert ArxivAdapter.source_type == "arxiv"

    def test_extract_paper_id_all_formats(self):
        """Verify paper ID extraction for common URL formats."""
        cases = [
            ("https://arxiv.org/abs/2603.00195", "2603.00195"),
            ("https://arxiv.org/pdf/2603.00195", "2603.00195"),
            ("https://arxiv.org/abs/2603.00195v1", "2603.00195v1"),
            ("https://arxiv.org/pdf/2603.00195v2", "2603.00195v2"),
            ("http://arxiv.org/abs/2301.01234", "2301.01234"),
        ]
        for url, expected in cases:
            assert _extract_paper_id(url) == expected, f"Failed for {url}"
