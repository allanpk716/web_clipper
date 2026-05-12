#!/bin/bash
# Build web-clip-helper Linux x86_64 binary using Docker
set -e

IMAGE="python:3.11-slim"
DIST_DIR="./dist"
SDK_DIR="/c/WorkSpace/agent/cli--agent-things/ai-agent-cli-rules/sdks/python"

echo "=== Building Linux x86_64 binary in Docker ==="

# Convert paths for Windows Docker
PROJECT_DIR="$(pwd -W 2>/dev/null || pwd)"
SDK_DIR_WIN="$(cd "$SDK_DIR" && pwd -W 2>/dev/null || echo "$SDK_DIR")"

MSYS_NO_PATHCONV=1 docker run --rm \
    -v "${PROJECT_DIR}":/src \
    -v "${SDK_DIR_WIN}":/sdk \
    -w /src \
    ${IMAGE} \
    bash -c '
set -e
echo "--- Installing system deps ---"
apt-get update -qq && apt-get install -y -qq binutils > /dev/null 2>&1

echo "--- Installing SDK ---"
pip install --quiet /sdk

echo "--- Installing PyInstaller ---"
pip install --quiet pyinstaller

echo "--- Installing web-clip-helper ---"
pip install --quiet -e .

echo "--- Running PyInstaller ---"
pyinstaller \
    --name web-clip-helper \
    --onefile \
    --clean \
    --noconfirm \
    --collect-all readability_lxml \
    --collect-all markdownify \
    --collect-all lxml \
    --collect-all charset_normalizer \
    --hidden-import web_clip_helper \
    --hidden-import web_clip_helper.cli \
    --hidden-import web_clip_helper.adapters \
    --hidden-import web_clip_helper.adapters._registry \
    --hidden-import web_clip_helper.adapters.base \
    --hidden-import web_clip_helper.adapters.generic \
    --hidden-import web_clip_helper.adapters.weibo \
    --hidden-import web_clip_helper.adapters.weibo_article \
    --hidden-import web_clip_helper.adapters.weibo_card \
    --hidden-import web_clip_helper.adapters.wechat \
    --hidden-import web_clip_helper.adapters.github \
    --hidden-import web_clip_helper.adapters.arxiv \
    --hidden-import web_clip_helper.logger \
    --hidden-import web_clip_helper.pipeline \
    --hidden-import web_clip_helper.output \
    --hidden-import web_clip_helper.crash \
    --hidden-import web_clip_helper.io_guard \
    --hidden-import web_clip_helper.models \
    --hidden-import web_clip_helper.index \
    --hidden-import web_clip_helper.storage \
    --hidden-import web_clip_helper.config \
    --hidden-import web_clip_helper.llm \
    --hidden-import web_clip_helper.images \
    --hidden-import web_clip_helper.paths \
    --hidden-import web_clip_helper.error_codes \
    --hidden-import web_clip_helper.url_utils \
    --hidden-import web_clip_helper.agent_schema \
    --hidden-import web_clip_helper.adapter \
    --hidden-import web_clip_helper.repository \
    --hidden-import web_clip_helper.services \
    --hidden-import typer \
    --hidden-import click \
    --hidden-import httpx \
    --hidden-import openai \
    --hidden-import yaml \
    --hidden-import platformdirs \
    --hidden-import agentsdk \
    src/web_clip_helper/cli.py

echo "--- Build complete ---"
ls -lh dist/web-clip-helper
chmod +x dist/web-clip-helper
'

echo ""
echo "=== Done ==="
ls -lh ${DIST_DIR}/
