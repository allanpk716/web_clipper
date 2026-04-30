---
id: T02
parent: S01
milestone: M003-dh8y4a
key_files:
  - scripts/test_real_urls.py
key_decisions:
  - (none)
duration: 
verification_result: untested
completed_at: 2026-04-30T05:09:14.104Z
blocker_discovered: false
---

# T02: 将 arxiv URL 加入集成测试脚本，dry-run 确认 26 URL 正确路由

**将 arxiv URL 加入集成测试脚本，dry-run 确认 26 URL 正确路由**

## What Happened

在 _extract_urls_from_manifests() 末尾添加 SUPPLEMENTARY_URLS 列表，包含 arxiv URL (https://arxiv.org/abs/2603.00195)。dry-run 确认 26 个 URL 正确路由到 5 种适配器类型：git_hub(4), weibo(19), we_chat(1), weibo_card(1), arxiv(1)。

## Verification

python scripts/test_real_urls.py --dry-run → 26 URLs, arxiv:1, exit 0

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| — | No verification commands discovered | — | — | — |

## Deviations

None.

## Known Issues

None.

## Files Created/Modified

- `scripts/test_real_urls.py`
