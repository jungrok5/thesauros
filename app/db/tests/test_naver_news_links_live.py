"""Live probe — does a Naver Finance 종목뉴스 link still resolve to a
real article body?

Context: 2026-05-22 — Naver retired the in-page news_read.naver viewer
and replaced it with a 92-byte <script>top.location.href=…</script>
stub. Mobile / in-app browsers don't follow that script, so users hit
a blank page. The TS parser was updated to build the n.news.naver.com
URL directly (commit bbf8855). But if Naver moves the URL format
AGAIN, only a live request can catch the breakage — a static unit
test against a fixture wouldn't.

This probe:
  1. fetches Naver's 종목뉴스 list for a high-traffic ticker
     (005930 = 삼성전자 — always has fresh items)
  2. runs the same parser the API route uses
  3. HTTP-fetches the first item's URL
  4. asserts the body is large enough to be a real article and
     doesn't contain the redirect-stub marker

Runs in the daily-scan data-quality step, so a Naver-side regression
shows up in the cron's end-ping with status=failure within ~24h.

Skipped when the runner can't reach finance.naver.com (no internet
in CI sandbox, etc.) — the GH Actions runner has full outbound, but
local dev or restricted CI shouldn't fail this test.
"""
from __future__ import annotations

import re
import urllib.request
import urllib.error

import pytest


# Identical fetch path to web-next/src/app/api/news/[ticker]/route.ts —
# if Naver blocks our cloud UA we need to know.
_NAVER_LIST_URL = (
    "https://finance.naver.com/item/news_news.naver"
    "?code={code}&page=1&sm=title_entity_id.basic&clusterId="
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36"
    ),
    "Referer": "https://finance.naver.com/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 005930 = 삼성전자 — picked because it has fresh news every day, so
# the test is not at risk of "list empty today" flake. If this ticker
# ever has no news (delisting, etc.), swap to 000660 SK하이닉스.
PROBE_CODE = "005930"


def _fetch(url: str, decode_as: str = "utf-8") -> tuple[int, str]:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
        text = body.decode(decode_as, errors="ignore")
        return r.status, text
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError) as e:
        pytest.skip(f"naver unreachable: {e}")
        raise  # unreachable; placates type checker


def _extract_first_article_href(html: str) -> str | None:
    """Mirror the parser's regex against `table.type5` rows."""
    table_m = re.search(
        r'<table[^>]*class="[^"]*type5[^"]*"[\s\S]*?</table>',
        html, re.I,
    )
    if not table_m:
        return None
    first_a = re.search(
        r'<td[^>]*class="[^"]*title[^"]*"[^>]*>\s*<a\s+[^>]*href="([^"]+)"',
        table_m.group(), re.I,
    )
    return first_a.group(1) if first_a else None


def _to_canonical(href: str) -> str:
    """Reproduce the URL rewrite from web-next/src/lib/news-parsers.ts."""
    article = re.search(r"[?&]article_id=([^&]+)", href)
    office = re.search(r"[?&]office_id=([^&]+)", href)
    if article and office:
        return (
            f"https://n.news.naver.com/mnews/article/"
            f"{office.group(1)}/{article.group(1)}"
        )
    if href.startswith("/"):
        return f"https://finance.naver.com{href}"
    return href


def test_naver_news_link_returns_real_article_body():
    """If the canonical URL doesn't resolve to a real article body,
    Naver has shifted its URL format again and the parser's rewrite
    needs updating. The 92-byte JS-redirect stub from 2026-05-22 is
    the canonical failure marker; we check for both 'too small' and
    'is a script-stub' to catch variants."""
    status, list_html = _fetch(_NAVER_LIST_URL.format(code=PROBE_CODE),
                                decode_as="euc-kr")
    assert status == 200, f"news list HTTP {status}"
    href = _extract_first_article_href(list_html)
    assert href, (
        "Naver 종목뉴스 list returned no parseable article row — "
        "either the page format changed (no table.type5) or "
        f"종목 {PROBE_CODE} has zero news today (pick another probe)"
    )
    canonical = _to_canonical(href)

    status, body = _fetch(canonical, decode_as="utf-8")
    assert status == 200, f"article URL {canonical} returned HTTP {status}"

    # A real n.news.naver.com article body is 30-150KB. The retired-
    # endpoint stub was 92 bytes. Pick a generous floor (5KB) — any
    # real article will clear it, but a stub redirect won't.
    assert len(body) > 5_000, (
        f"article body suspiciously small ({len(body)} bytes) at "
        f"{canonical} — Naver may have introduced another redirect "
        f"layer. Body preview: {body[:200]!r}"
    )

    # Explicit stub detector — catches the 2026-05-22 regression by
    # name even if the body somehow grows past 5KB.
    assert "top.location.href" not in body[:500], (
        f"article URL {canonical} returned a JS-redirect stub instead "
        f"of real content. Parser rewrite needs updating."
    )
