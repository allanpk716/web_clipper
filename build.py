#!/usr/bin/env python3
"""Build web-clip-helper as standalone executables using PyInstaller.

Usage:
    python build.py              # Build for current platform
    python build.py --clean      # Clean build artifacts first
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def clean():
    """Remove build artifacts."""
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)
            print(f"Cleaned {d}")


def build():
    """Run PyInstaller to create standalone executable."""
    # Ensure package is importable
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-e", "."],
        cwd=ROOT,
    )

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "web-clip-helper",
        "--onefile",
        "--clean",
        "--noconfirm",
        # Collect data that packages might need
        "--collect-all", "readability_lxml",
        "--collect-all", "markdownify",
        "--collect-all", "lxml",
        "--collect-all", "charset_normalizer",
        "--hidden-import", "web_clip_helper",
        "--hidden-import", "web_clip_helper.cli",
        "--hidden-import", "web_clip_helper.adapters",
        "--hidden-import", "web_clip_helper.adapters._registry",
        "--hidden-import", "web_clip_helper.adapters.base",
        "--hidden-import", "web_clip_helper.adapters.generic",
        "--hidden-import", "web_clip_helper.adapters.weibo",
        "--hidden-import", "web_clip_helper.adapters.weibo_article",
        "--hidden-import", "web_clip_helper.adapters.weibo_card",
        "--hidden-import", "web_clip_helper.adapters.wechat",
        "--hidden-import", "web_clip_helper.adapters.github",
        "--hidden-import", "web_clip_helper.adapters.arxiv",
        "--hidden-import", "web_clip_helper.logger",
        "--hidden-import", "web_clip_helper.pipeline",
        "--hidden-import", "web_clip_helper.output",
        "--hidden-import", "web_clip_helper.crash",
        "--hidden-import", "web_clip_helper.io_guard",
        "--hidden-import", "web_clip_helper.models",
        "--hidden-import", "web_clip_helper.index",
        "--hidden-import", "web_clip_helper.storage",
        "--hidden-import", "web_clip_helper.config",
        "--hidden-import", "web_clip_helper.llm",
        "--hidden-import", "web_clip_helper.images",
        "--hidden-import", "web_clip_helper.paths",
        "--hidden-import", "web_clip_helper.error_codes",
        "--hidden-import", "web_clip_helper.url_utils",
        "--hidden-import", "web_clip_helper.agent_schema",
        "--hidden-import", "web_clip_helper.adapter",
        "--hidden-import", "web_clip_helper.repository",
        "--hidden-import", "web_clip_helper.services",
        "--hidden-import", "web_clip_helper.services.import_service",
        "--hidden-import", "typer",
        "--hidden-import", "click",
        "--hidden-import", "httpx",
        "--hidden-import", "openai",
        "--hidden-import", "pyyaml",
        "--hidden-import", "platformdirs",
        "--hidden-import", "agentsdk",
        # CLI entry point
        f"{ROOT / 'src' / 'web_clip_helper' / 'cli.py'}",
    ]

    print(f"\nBuilding: {' '.join(cmd[:6])}...")
    subprocess.check_call(cmd, cwd=ROOT)

    exe_name = "web-clip-helper.exe" if sys.platform == "win32" else "web-clip-helper"
    exe_path = DIST / exe_name
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n✅ Built: {exe_path} ({size_mb:.1f} MB)")
    else:
        print(f"\n❌ Build failed: {exe_path} not found")
        sys.exit(1)


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
    build()
