"""Arxiv adapter — fetch paper metadata, download PDF, generate Chinese summary.

URL pattern: ``https?://arxiv\\.org/(abs|pdf)/.+``

Strategy:
1. Extract the arxiv paper ID from the URL (handles both /abs/ and /pdf/ paths).
2. Fetch the abs page HTML and parse metadata (title, authors, abstract,
   categories, submission date) from ``<meta>`` tags.
3. Download the PDF binary from ``arxiv.org/pdf/{id}.pdf``.
4. Call LLM to generate a Chinese summary of the abstract (non-fatal on failure).
5. Build content_md with metadata header + Chinese summary + English abstract.
6. Return RawContent with PDF in ``extra_files``.

Key decisions:
- D011: PDF archival + summary mode
- D012: PDF download failure = entire clip fails
- Timeout 60s (larger than default 30s for large PDF files)
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx

from .base import AdapterError, register_adapter
from ..config import get_config
from ..llm import LLMClient
from ..models import RawContent
from ..output import jsonl_emit_progress, jsonl_emit_warning

__all__ = ["ArxivAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_URL_PATTERN = r"https?://arxiv\.org/(abs|pdf)/.+"
_TIMEOUT = 60.0

# Regex to extract arxiv paper ID from URL.
# Matches: 2603.00195, 2603.00195v1, 2301.01234v2, etc.
_PAPER_ID_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)

# HTML parsing patterns for the abs page
_META_TITLE_RE = re.compile(
    r'<meta\s+name="citation_title"\s+content="([^"]+)"', re.IGNORECASE
)
_META_AUTHOR_RE = re.compile(
    r'<meta\s+name="citation_author"\s+content="([^"]+)"', re.IGNORECASE
)
_META_DATE_RE = re.compile(
    r'<meta\s+name="citation_date"\s+content="([^"]+)"', re.IGNORECASE
)
_ABSTRACT_BLOCK_RE = re.compile(
    r'<blockquote\s+class="abstract[^"]*">\s*'
    r'<span\s+class="descriptor">Abstract:</span>\s*'
    r"(.*?)</blockquote>",
    re.DOTALL | re.IGNORECASE,
)
_PRIMARY_SUBJECT_RE = re.compile(
    r'<span\s+class="primary-subject">([^<]+)</span>', re.IGNORECASE
)
_CATEGORIES_RE = re.compile(
    r'<meta\s+name="citation_arxiv_category"\s+content="([^"]+)"', re.IGNORECASE
)


def _extract_paper_id(url: str) -> str:
    """Extract arxiv paper ID from URL.

    Handles both ``/abs/`` and ``/pdf/`` paths, and versioned IDs
    like ``2603.00195v1``.

    Parameters
    ----------
    url:
        Full arxiv URL (e.g. ``https://arxiv.org/abs/2603.00195``).

    Returns
    -------
    str
        The paper ID (e.g. ``2603.00195``).

    Raises
    ------
    AdapterError
        If the paper ID cannot be extracted from the URL.
    """
    m = _PAPER_ID_RE.search(url)
    if m:
        return m.group(1)
    raise AdapterError(f"Cannot extract arxiv paper ID from URL: {url}")


def _sanitize_filename(title: str) -> str:
    """Sanitize a paper title for use as a PDF filename.

    Keeps alphanumeric, CJK, spaces, hyphens, underscores, and dots.
    Replaces everything else with underscore, collapses runs, and
    truncates to 200 chars.
    """
    # Keep word chars, CJK, spaces, hyphens, underscores, dots
    sanitized = re.sub(r'[^\w\s\-.\u4e00-\u9fff]', '_', title)
    # Collapse consecutive underscores
    sanitized = re.sub(r'_+', '_', sanitized)
    # Strip leading/trailing underscores and whitespace
    sanitized = sanitized.strip('_ \t')
    # Truncate
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized or "untitled"


def _fetch_abs_page(client: httpx.Client, paper_id: str) -> str:
    """Fetch the arxiv abs page HTML.

    Parameters
    ----------
    client:
        An httpx client with appropriate timeout.
    paper_id:
        The arxiv paper ID.

    Returns
    -------
    str
        The HTML text of the abs page.

    Raises
    ------
    AdapterError
        If the fetch fails.
    """
    url = f"https://arxiv.org/abs/{paper_id}"
    jsonl_emit_progress(
        message=f"Fetching arxiv abs page: {paper_id}",
        stage="fetch",
        url=url,
    )
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        msg = f"arxiv abs page returned HTTP {status} for {url}"
        code = "NOT_FOUND" if status in (404, 410) else "FETCH_ERROR"
        raise AdapterError(msg, error_code=code, url=url) from exc
    except httpx.TimeoutException as exc:
        msg = f"Timeout fetching arxiv abs page {url} (>{_TIMEOUT}s)"
        raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc
    except httpx.RequestError as exc:
        msg = f"Network error fetching arxiv abs page {url}: {exc}"
        raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc


def _parse_metadata(html: str) -> dict:
    """Parse the arxiv abs page HTML to extract metadata.

    Uses ``<meta>`` tags and the ``<blockquote class="abstract">`` block.

    Parameters
    ----------
    html:
        The HTML text of the abs page.

    Returns
    -------
    dict
        Keys: title, authors (list[str]), abstract (str),
        categories (list[str]), date (str).
    """
    # Title
    m = _META_TITLE_RE.search(html)
    title = m.group(1).strip() if m else "Untitled"

    # Authors
    authors = [a.strip() for a in _META_AUTHOR_RE.findall(html)]

    # Date
    m = _META_DATE_RE.search(html)
    date = m.group(1).strip() if m else ""

    # Abstract — strip HTML tags
    m = _ABSTRACT_BLOCK_RE.search(html)
    if m:
        abstract_raw = m.group(1)
        # Remove HTML tags
        abstract = re.sub(r"<[^>]+>", "", abstract_raw).strip()
        # Collapse whitespace
        abstract = re.sub(r"\s+", " ", abstract)
    else:
        abstract = ""

    # Categories — primary subject + all meta category tags
    categories: list[str] = []
    m = _PRIMARY_SUBJECT_RE.search(html)
    if m:
        primary = m.group(1).strip()
        categories.append(primary)
    for cat in _CATEGORIES_RE.findall(html):
        cat = cat.strip()
        if cat not in categories:
            categories.append(cat)

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "categories": categories,
        "date": date,
    }


def _download_pdf(client: httpx.Client, paper_id: str) -> bytes:
    """Download the PDF binary from arxiv.

    Parameters
    ----------
    client:
        An httpx client with appropriate timeout.
    paper_id:
        The arxiv paper ID (version suffix is preserved).

    Returns
    -------
    bytes
        Raw PDF bytes.

    Raises
    ------
    AdapterError
        If the download fails or response is not PDF (D012).
    """
    url = f"https://arxiv.org/pdf/{paper_id}.pdf"
    jsonl_emit_progress(
        message=f"Downloading arxiv PDF: {paper_id}",
        stage="fetch",
        url=url,
    )
    try:
        resp = client.get(url)
        resp.raise_for_status()

        # Validate content type
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" not in content_type and not resp.content[:5].startswith(b"%PDF-"):
            msg = (
                f"arxiv PDF download returned non-PDF content "
                f"(content-type: {content_type}) for {url}"
            )
            raise AdapterError(msg, error_code="FETCH_ERROR", url=url)

        jsonl_emit_progress(
            message=f"PDF downloaded: {len(resp.content):,} bytes",
            stage="fetch",
            url=url,
            size_bytes=len(resp.content),
        )
        return resp.content

    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        msg = (
            f"arxiv PDF download failed with HTTP {status} "
            f"for {url}"
        )
        code = "NOT_FOUND" if status in (404, 410) else "FETCH_ERROR"
        raise AdapterError(msg, error_code=code, url=url) from exc
    except httpx.TimeoutException as exc:
        msg = f"Timeout downloading arxiv PDF {url} (>{_TIMEOUT}s)"
        raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc
    except httpx.RequestError as exc:
        msg = f"Network error downloading arxiv PDF {url}: {exc}"
        raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc


def _generate_chinese_summary(abstract: str, title: str) -> str:
    """Use LLM to generate a Chinese summary of the paper abstract.

    Non-fatal — returns empty string on any failure (missing API key,
    network error, timeout, malformed response).

    Parameters
    ----------
    abstract:
        The English abstract text.
    title:
        The paper title.

    Returns
    -------
    str
        Chinese summary, or empty string on failure.
    """
    if not abstract.strip():
        return ""

    config = get_config()
    if not config.llm.api_key.strip():
        jsonl_emit_warning(
            message="LLM API key not configured, skipping Chinese summary",
            stage="llm",
        )
        return ""

    jsonl_emit_progress(
        message="Generating Chinese summary via LLM",
        stage="llm",
    )

    try:
        client = LLMClient(config.llm)
        prompt = (
            "请用中文概括以下学术论文的摘要。要求：\n"
            "1. 用2-3段简洁的中文概括论文的核心内容和贡献\n"
            "2. 保持学术性和准确性\n"
            "3. 不要添加原文没有的信息\n"
            "4. 不要加任何前缀如'概括：'等\n\n"
            f"论文标题：{title}\n\n"
            f"摘要：\n{abstract}"
        )
        # Use _chat directly for a longer response
        openai_client = client._get_client()
        resp = openai_client.chat.completions.create(
            model=config.llm.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
        )
        choice = resp.choices[0]
        if choice.message and choice.message.content:
            summary = choice.message.content.strip()
            if summary:
                jsonl_emit_progress(
                    message="Chinese summary generated successfully",
                    stage="llm",
                    length=len(summary),
                )
                return summary

        jsonl_emit_warning(
            message="LLM returned empty response for Chinese summary",
            stage="llm",
        )
        return ""

    except Exception as exc:
        jsonl_emit_warning(
            message=f"LLM Chinese summary failed (non-fatal): {exc}",
            stage="llm",
            error=str(exc),
        )
        return ""


@register_adapter(_URL_PATTERN)
class ArxivAdapter:
    """Adapter for arxiv.org paper URLs.

    Handles ``arxiv.org/abs/{id}`` and ``arxiv.org/pdf/{id}`` URLs.
    Fetches metadata from the abs page, downloads PDF, and optionally
    generates a Chinese summary of the abstract via LLM.

    Returns a :class:`RawContent` with ``source_type="arxiv"`` and the
    PDF stored in ``extra_files``.
    """

    source_type = "arxiv"

    def fetch(self, url: str) -> RawContent:
        """Fetch an arxiv paper: metadata, PDF, and Chinese summary.

        Parameters
        ----------
        url:
            An arxiv URL (e.g. ``https://arxiv.org/abs/2603.00195``).

        Returns
        -------
        RawContent
            Paper metadata + Chinese summary + English abstract in markdown,
            with PDF binary in ``extra_files``.

        Raises
        ------
        AdapterError
            If the abs page or PDF cannot be fetched (D012).
        """
        paper_id = _extract_paper_id(url)

        jsonl_emit_progress(
            message=f"Clipping arxiv paper: {paper_id}",
            stage="fetch",
            url=url,
        )

        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            # Step 1: Fetch and parse abs page
            html = _fetch_abs_page(client, paper_id)
            metadata = _parse_metadata(html)

            # Step 2: Download PDF
            pdf_bytes = _download_pdf(client, paper_id)

        # Step 3: Generate Chinese summary (non-fatal)
        chinese_summary = _generate_chinese_summary(
            abstract=metadata["abstract"],
            title=metadata["title"],
        )

        # Step 4: Build content_md
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        authors_str = ", ".join(metadata["authors"]) if metadata["authors"] else "Unknown"
        categories_str = ", ".join(metadata["categories"]) if metadata["categories"] else ""
        date_str = metadata["date"] or "Unknown"

        header_lines = [
            f"> Source: {url}",
            f"> Clipped: {timestamp}",
            f"> Authors: {authors_str}",
        ]
        if categories_str:
            header_lines.append(f"> Categories: {categories_str}")
        header_lines.append(f"> Submitted: {date_str}")

        header = "\n".join(header_lines)

        # Build summary section (only if we got a Chinese summary)
        summary_section = ""
        if chinese_summary:
            summary_section = f"\n---\n\n## \u6458\u8981 / Summary\n\n{chinese_summary}\n"

        # Build abstract section
        abstract_section = ""
        if metadata["abstract"]:
            abstract_section = f"\n---\n\n## Abstract\n\n{metadata['abstract']}\n"

        content_md = f"{header}\n{summary_section}{abstract_section}"

        # Step 5: Build extra_files with sanitized PDF filename
        pdf_filename = _sanitize_filename(metadata["title"]) + ".pdf"
        extra_files = {pdf_filename: pdf_bytes}

        jsonl_emit_progress(
            message=f"Arxiv clip complete: {paper_id}",
            stage="fetch",
            url=url,
            pdf_size=len(pdf_bytes),
            has_chinese_summary=bool(chinese_summary),
        )

        return RawContent(
            url=url,
            title=metadata["title"],
            content_md=content_md,
            images=[],
            source_type=self.source_type,
            extra_files=extra_files,
        )
