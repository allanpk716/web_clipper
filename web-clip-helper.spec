# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ['web_clip_helper', 'web_clip_helper.cli', 'web_clip_helper.adapters', 'web_clip_helper.adapters._registry', 'web_clip_helper.adapters.base', 'web_clip_helper.adapters.generic', 'web_clip_helper.adapters.weibo', 'web_clip_helper.adapters.weibo_article', 'web_clip_helper.adapters.weibo_card', 'web_clip_helper.adapters.wechat', 'web_clip_helper.adapters.github', 'web_clip_helper.adapters.arxiv', 'web_clip_helper.logger', 'web_clip_helper.pipeline', 'web_clip_helper.output', 'web_clip_helper.crash', 'web_clip_helper.io_guard', 'web_clip_helper.models', 'web_clip_helper.index', 'web_clip_helper.storage', 'web_clip_helper.config', 'web_clip_helper.llm', 'web_clip_helper.images', 'web_clip_helper.paths', 'web_clip_helper.error_codes', 'web_clip_helper.url_utils', 'web_clip_helper.agent_schema', 'web_clip_helper.adapter', 'web_clip_helper.repository', 'web_clip_helper.services', 'typer', 'click', 'httpx', 'openai', 'yaml', 'platformdirs', 'agentsdk']
tmp_ret = collect_all('readability_lxml')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('markdownify')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('lxml')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('charset_normalizer')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['src/web_clip_helper/cli.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='web-clip-helper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
