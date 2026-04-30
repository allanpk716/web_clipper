---
sliceId: S03
uatType: artifact-driven
verdict: PASS
date: 2026-04-29T10:16:03.000Z
---

# UAT Result — S03

## Checks

| Check | Mode | Result | Notes |
|-------|------|--------|-------|
| Smoke test — dry-run URL classification | runtime | PASS | `python scripts/test_real_urls.py --dry-run` → 25 URLs classified: git_hub(4), weibo(19), we_chat(1), weibo_card(1), exit 0 |
| 1. Full integration test — all 25 URLs | runtime | PASS | `python scripts/test_real_urls.py` → 25/25 passed (100%), exit 0. ~3 min execution with 2s weibo rate-limit delays. |
| 2. Report accuracy | runtime | PASS | `integration_report.json` aggregate: total=25, passed=25, failed=0, pass_rate=100.0% |
| 3. GitHub adapter (4 URLs) | runtime | PASS | 4/4 passed. content_md_length range: 3,788–21,176 chars (README content extracted). |
| 4. Weibo adapter (19 URLs) | runtime | PASS | 19/19 passed. content_md_length range: 541–7,868 chars. Referer header fix confirmed working. |
| 5. WeChat adapter (1 URL) | runtime | PASS | 1/1 passed. content_md_length=3,711 chars, image_count=3. HTML stripping fix confirmed. |
| 6. WeiboCard adapter (1 URL) | runtime | PASS | 1/1 passed. content_md_length=9,105 chars, image_count=11. str() comparison fix confirmed. |
| 7. Unit test regression | runtime | PASS | `python -m pytest tests/ -q --tb=no` → 457 passed, 0 failed, exit 0 |
| Edge case: Windows console encoding | runtime | PASS | No UnicodeEncodeError — script reconfigures stdout to UTF-8 on startup |
| Edge case: Rate limiting | runtime | PASS | 2s delays between weibo-family requests prevented HTTP 429 responses |

## Overall Verdict

PASS — All 7 UAT test cases and 2 edge case checks passed. 25/25 real URLs clipped successfully across 4 adapter types (GitHub, Weibo, WeChat, WeiboCard). 457/457 unit tests pass with zero regressions. Three production bugs discovered and fixed during execution (Weibo Referer, WeiboCard string comparison, WeChat HTML stripping).

## Notes

- Initial run was 5/25 (20%) — three bugs were identified and fixed before the final successful run
- Arxiv adapter not included in this test batch (no arxiv URLs in baseline data; tested separately in S02 UAT)
- Reports overwritten on each run — `integration_report.json` and `integration_report.md` reflect the final clean run
- Weibo API access depends on Referer header — may break if API policy changes
