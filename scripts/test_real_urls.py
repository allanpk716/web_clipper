#!/usr/bin/env python
"""Integration test script — run clip_url() against 25+ real URLs from baseline data.

Extracts test URLs from docs/exsample/my-things/ baseline data, routes each through
the adapter framework, runs clip_url() against each URL, and generates JSON + Markdown
reports with per-URL results and aggregate statistics.

Usage:
    python scripts/test_real_urls.py                  # run all URLs
    python scripts/test_real_urls.py --dry-run        # list URLs + routing only
    python scripts/test_real_urls.py --category weibo # run only weibo-family URLs
    python scripts/test_real_urls.py --output-dir /tmp/test-clips  # custom storage
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ── Ensure src is importable ──────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ── URL extraction ────────────────────────────────────────────────────

BASELINE_DIR = PROJECT_ROOT / "docs" / "exsample" / "my-things"


@dataclass
class TestURL:
    """A single test URL with provenance metadata."""

    url: str
    source_type: str  # adapter type from manifest / content inference
    folder: str  # baseline folder that contributed this URL
    manifest: str  # "static" or "dynamic"
    adapter_type: str = ""  # set by _route_urls()


def _extract_urls_from_manifests() -> list[TestURL]:
    """Extract test URLs from _manifest.json files and .md content.

    Strategy:
    1. Dynamic manifest → GitHub URLs directly.
    2. Static: scan ALL directories under static/, extract URLs from .md files
       using 链接/来源/原文链接 headers.  For directories referenced in the
       static manifest, use its source_type; for others, derive from adapter
       routing.
    """
    urls: list[TestURL] = []

    # ── Dynamic manifest → GitHub URLs ────────────────────────────
    dynamic_manifest_path = BASELINE_DIR / "dynamic" / "_manifest.json"
    if dynamic_manifest_path.exists():
        data = json.loads(dynamic_manifest_path.read_text(encoding="utf-8"))
        for item in data.get("repos", []):
            urls.append(
                TestURL(
                    url=item["url"],
                    source_type=item["source_type"],
                    folder=item["folder"],
                    manifest="dynamic",
                )
            )

    # ── Static: scan ALL directories, not just manifest entries ───
    static_manifest_path = BASELINE_DIR / "static" / "_manifest.json"
    static_dir = BASELINE_DIR / "static"

    # Build manifest lookup by date prefix for source_type hints
    manifest_items: dict[str, dict] = {}
    if static_manifest_path.exists():
        manifest_data = json.loads(static_manifest_path.read_text(encoding="utf-8"))
        for item in manifest_data.get("items", []):
            date_prefix = item["folder"][:10]  # "2026-04-11"
            manifest_items[date_prefix] = item

    if static_dir.exists():
        for dir_path in sorted(static_dir.iterdir()):
            if not dir_path.is_dir() or dir_path.name.startswith("."):
                continue

            # Find .md files in this directory
            md_files = list(dir_path.glob("*.md"))
            if not md_files:
                continue
            md_text = md_files[0].read_text(encoding="utf-8")
            folder_name = dir_path.name

            # Get source_type from manifest if available, else "auto"
            date_prefix = dir_path.name[:10]
            manifest_entry = manifest_items.get(date_prefix)
            source_type = manifest_entry["source_type"] if manifest_entry else "auto"

            # Extract URL from content using priority order:
            # 1. **来源**: <http-url>  (card.weibo) — only if value starts with http
            # 2. **链接**: <url>  (weibo)
            # 3. 原文链接: <url>  (wechat)
            url = None

            # Check **来源** — only accept if it's an actual URL
            m = re.search(r"\*\*来源\*\*:\s*(\S+)", md_text)
            if m and m.group(1).startswith("http"):
                url = m.group(1)

            if not url:
                m = re.search(r"\*\*链接\*\*:\s*(\S+)", md_text)
                if m:
                    url = m.group(1)

            if not url:
                m = re.search(r"原文链接:\s*(\S+)", md_text)
                if m:
                    url = m.group(1)

            if url:
                urls.append(
                    TestURL(
                        url=url,
                        source_type=source_type,
                        folder=folder_name,
                        manifest="static",
                    )
                )

    # ── Supplementary URLs not in baseline data ──────────────────
    # Arxiv and other adapters that have no corresponding baseline folder
    SUPPLEMENTARY_URLS = [
        {
            "url": "https://arxiv.org/abs/2603.00195",
            "source_type": "arxiv",
            "folder": "supplementary",
            "manifest": "supplementary",
        },
    ]
    for item in SUPPLEMENTARY_URLS:
        urls.append(TestURL(**item))

    return urls


# ── Adapter routing ───────────────────────────────────────────────────


def _route_urls(urls: list[TestURL]) -> list[TestURL]:
    """Assign adapter_type to each URL via route_url()."""
    # Import here so --dry-run still works without full env
    from web_clip_helper.adapter import route_url  # noqa: F811
    import web_clip_helper.adapters._registry  # noqa: F401

    for t in urls:
        try:
            cls = route_url(t.url)
            # Derive adapter type from class name: WeiboAdapter → weibo
            name = cls.__name__
            if name.endswith("Adapter"):
                name = name[: -len("Adapter")]
            elif name == "_GenericAdapter":
                name = "generic"
            # Convert CamelCase to snake_case
            adapter_type = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
            t.adapter_type = adapter_type
        except ValueError:
            t.adapter_type = "unknown"
    return urls


# ── Test execution ────────────────────────────────────────────────────

# Adapters that need a delay between consecutive requests
_WEIBO_FAMILY = {"weibo", "weibo_card", "weibo_headline"}
_DELAY_SECONDS = 2.0


@dataclass
class URLResult:
    """Result of clipping a single URL."""

    url: str
    adapter_type: str
    status: str  # "success", "fail", "error"
    content_md_length: int = 0
    image_count: int = 0
    extra_files_count: int = 0
    error: str = ""
    elapsed_ms: float = 0.0
    folder: str = ""
    title: str = ""


def _run_clip(t: TestURL, config) -> URLResult:
    """Run clip_url() for a single TestURL and return the result."""
    from web_clip_helper.pipeline import clip_url

    start = time.monotonic()
    try:
        result = clip_url(t.url, config)
        elapsed = (time.monotonic() - start) * 1000

        if result is None:
            return URLResult(
                url=t.url,
                adapter_type=t.adapter_type,
                status="fail",
                elapsed_ms=elapsed,
                folder=t.folder,
            )

        # Read the markdown file to get content length
        md_text = ""
        if result.markdown_path and result.markdown_path.exists():
            md_text = result.markdown_path.read_text(encoding="utf-8")

        # Extract title from first heading in markdown
        title = ""
        title_m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
        if title_m:
            title = title_m.group(1).strip()

        # Count images in storage folder
        image_count = result.image_count
        extra_count = result.file_count if hasattr(result, "file_count") else 0

        return URLResult(
            url=t.url,
            adapter_type=t.adapter_type,
            status="success",
            content_md_length=len(md_text),
            image_count=image_count,
            extra_files_count=extra_count,
            elapsed_ms=elapsed,
            folder=t.folder,
            title=title,
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return URLResult(
            url=t.url,
            adapter_type=t.adapter_type,
            status="error",
            error=str(exc),
            elapsed_ms=elapsed,
            folder=t.folder,
        )


def _run_all(urls: list[TestURL], config) -> list[URLResult]:
    """Run clip_url for all URLs, inserting delays between weibo-family requests."""
    from web_clip_helper.pipeline import clip_url  # noqa: F401

    results: list[URLResult] = []
    last_was_weibo = False

    for i, t in enumerate(urls):
        if last_was_weibo and t.adapter_type in _WEIBO_FAMILY:
            print(f"  ⏳ Delaying {_DELAY_SECONDS}s (weibo rate limit)...")
            time.sleep(_DELAY_SECONDS)

        print(f"  [{i + 1}/{len(urls)}] {t.adapter_type}: {t.url[:80]}...")
        result = _run_clip(t, config)
        status_icon = "✅" if result.status == "success" else "❌"
        print(f"    {status_icon} {result.status} ({result.elapsed_ms:.0f}ms)")
        if result.error:
            print(f"    Error: {result.error[:120]}")

        results.append(result)
        last_was_weibo = t.adapter_type in _WEIBO_FAMILY

    return results


# ── Report generation ─────────────────────────────────────────────────


@dataclass
class AggregateReport:
    """Aggregate statistics across all URL results."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    by_adapter: dict = field(default_factory=dict)


def _compute_aggregate(results: list[URLResult]) -> AggregateReport:
    """Compute aggregate statistics from results."""
    report = AggregateReport()
    report.total = len(results)
    report.passed = sum(1 for r in results if r.status == "success")
    report.failed = sum(1 for r in results if r.status == "fail")
    report.errors = sum(1 for r in results if r.status == "error")
    report.pass_rate = (
        round(report.passed / report.total * 100, 1) if report.total else 0.0
    )

    # Break down by adapter type
    by_adapter: dict[str, dict] = {}
    for r in results:
        adapter = r.adapter_type
        if adapter not in by_adapter:
            by_adapter[adapter] = {"total": 0, "passed": 0, "failed": 0, "errors": 0}
        by_adapter[adapter]["total"] += 1
        if r.status == "success":
            by_adapter[adapter]["passed"] += 1
        elif r.status == "fail":
            by_adapter[adapter]["failed"] += 1
        else:
            by_adapter[adapter]["errors"] += 1
    report.by_adapter = by_adapter

    return report


def _write_json_report(
    results: list[URLResult],
    aggregate: AggregateReport,
    output_path: Path,
) -> None:
    """Write machine-readable JSON report."""
    data = {
        "aggregate": asdict(aggregate),
        "results": [asdict(r) for r in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_markdown_report(
    results: list[URLResult],
    aggregate: AggregateReport,
    output_path: Path,
) -> None:
    """Write human-readable Markdown report."""
    lines: list[str] = []

    lines.append("# Integration Test Report")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total URLs | {aggregate.total} |")
    lines.append(f"| Passed | {aggregate.passed} ✅ |")
    lines.append(f"| Failed | {aggregate.failed} ❌ |")
    lines.append(f"| Errors | {aggregate.errors} 💥 |")
    lines.append(f"| Pass Rate | {aggregate.pass_rate}% |")
    lines.append("")

    # By adapter type
    lines.append("## Breakdown by Adapter Type")
    lines.append("")
    lines.append("| Adapter | Total | Passed | Failed | Errors | Pass Rate |")
    lines.append("|---------|-------|--------|--------|--------|-----------|")
    for adapter, stats in sorted(aggregate.by_adapter.items()):
        rate = (
            round(stats["passed"] / stats["total"] * 100, 1)
            if stats["total"]
            else 0.0
        )
        lines.append(
            f"| {adapter} | {stats['total']} | {stats['passed']} | {stats['failed']} | {stats['errors']} | {rate}% |"
        )
    lines.append("")

    # Per-URL results
    lines.append("## Per-URL Results")
    lines.append("")
    lines.append("| # | Status | Adapter | URL | Content Length | Images | Time (ms) | Error |")
    lines.append("|---|--------|---------|-----|----------------|--------|-----------|-------|")
    for i, r in enumerate(results, 1):
        icon = "✅" if r.status == "success" else ("❌" if r.status == "fail" else "💥")
        url_short = r.url[:60] + "..." if len(r.url) > 60 else r.url
        error_short = r.error[:50] + "..." if len(r.error) > 50 else r.error
        lines.append(
            f"| {i} | {icon} {r.status} | {r.adapter_type} | {url_short} | {r.content_md_length} | {r.image_count} | {r.elapsed_ms:.0f} | {error_short} |"
        )
    lines.append("")

    # Failure details
    failures = [r for r in results if r.status != "success"]
    if failures:
        lines.append("## Failure Details")
        lines.append("")
        for i, r in enumerate(failures, 1):
            lines.append(f"### {i}. {r.adapter_type}: {r.url[:80]}")
            lines.append(f"- **Status**: {r.status}")
            if r.error:
                lines.append(f"- **Error**: {r.error}")
            lines.append(f"- **Elapsed**: {r.elapsed_ms:.0f}ms")
            lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────


def main() -> None:
    # Fix Windows console encoding for emoji output
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Integration test: clip 25+ real URLs from baseline data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List URLs + routing without fetching",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Run only URLs matching this adapter type (e.g. weibo, github)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for temp storage (default: temp dir)",
    )
    args = parser.parse_args()

    # 1. Extract URLs
    print("📋 Extracting test URLs from baseline data...")
    urls = _extract_urls_from_manifests()
    print(f"   Found {len(urls)} URLs from manifests")

    # 2. Route URLs to adapters
    print("🔗 Routing URLs to adapters...")
    urls = _route_urls(urls)

    # 3. Filter by category if specified
    if args.category:
        urls = [u for u in urls if args.category in u.adapter_type]
        print(f"   Filtered to {len(urls)} URLs matching '{args.category}'")

    # Print URL table
    print()
    print(f"{'#':>3}  {'Adapter':<20}  {'URL':<80}  {'Source':<10}")
    print("-" * 120)
    for i, t in enumerate(urls, 1):
        print(f"{i:>3}  {t.adapter_type:<20}  {t.url[:80]:<80}  {t.manifest:<10}")
    print()

    if args.dry_run:
        # Count by adapter type
        by_type: dict[str, int] = {}
        for t in urls:
            by_type[t.adapter_type] = by_type.get(t.adapter_type, 0) + 1
        print("📊 Adapter distribution:")
        for adapter, count in sorted(by_type.items()):
            print(f"   {adapter}: {count}")
        print(f"\n✅ Dry run complete — {len(urls)} URLs found and routed")
        sys.exit(0)

    # 4. Set up config
    import tempfile

    from web_clip_helper.config import Config

    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="web-clip-inttest-"))

    config = Config.load()
    config.storage_path = str(output_dir / "clips")
    config.db_path = str(output_dir / "clips.db")
    # Ensure storage dirs exist
    Path(config.storage_path).mkdir(parents=True, exist_ok=True)

    print(f"📂 Storage: {config.storage_path}")
    print()

    # 5. Run clips
    print("🚀 Running clip_url() for all URLs...")
    results = _run_all(urls, config)
    print()

    # 6. Compute aggregate
    aggregate = _compute_aggregate(results)

    # 7. Write reports
    report_dir = PROJECT_ROOT / "scripts"
    json_path = report_dir / "integration_report.json"
    md_path = report_dir / "integration_report.md"

    _write_json_report(results, aggregate, json_path)
    _write_markdown_report(results, aggregate, md_path)

    print(f"📊 Results: {aggregate.passed}/{aggregate.total} passed ({aggregate.pass_rate}%)")
    print(f"📄 JSON report: {json_path}")
    print(f"📄 Markdown report: {md_path}")

    # 8. Exit code
    if aggregate.failed > 0 or aggregate.errors > 0:
        print(f"\n❌ {aggregate.failed + aggregate.errors} URL(s) failed")
        sys.exit(1)
    else:
        print("\n✅ All URLs passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
