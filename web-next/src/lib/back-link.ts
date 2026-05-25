/**
 * Decide where a "back" link on a stock-detail-style page should point.
 *
 * Two signal sources (in priority order):
 *   1. Explicit URL param `?from=...` — the originating page sets this
 *      on its stock-link <Link href> so the destination doesn't depend
 *      on the Referer header (which Next.js client navigation can drop
 *      or send the WRONG page).
 *   2. Referer header — fallback for direct visits, shared links, etc.
 *      Same matching as the param does.
 *
 * The param fix is critical: pre-2026-05-21, this function relied ONLY
 * on Referer and a re-occurring regression was "스크리너 → 종목 상세
 * → 뒤로가기가 종목 검색으로 감". Root cause: RSC navigation can fetch
 * the page with no Referer, or with the upstream page (e.g. originating
 * /screener) replaced by the in-app prefetch URL. Explicit `from=` puts
 * the call-site in control.
 *
 * Behavior (first match wins):
 *   /watchlist        → "관심 종목으로"
 *   /screener         → "스크리너로"       (preserves ?preset=…)
 *   anything else     → "종목 검색"  (default)
 *
 * URL `?from=` values that the originating page should set:
 *   from=watchlist
 *   from=screener     (optionally + &preset=…)
 *   from=stocks       (no-op — equals the default)
 */
export type BackLink = { href: string; label: string };

const DEFAULT_BACK: BackLink = { href: "/stocks", label: "종목 검색" };

const PATH_RULES: Array<{ prefix: string; back: BackLink }> = [
  { prefix: "/watchlist",     back: { href: "/watchlist",     label: "관심 종목으로" } },
  { prefix: "/screener",      back: { href: "/screener",      label: "스크리너로" } },
];

/** Explicit param-based decision — preferred path. Each rule maps a
 *  `from` value (set by the originating page) to a label + URL,
 *  optionally taking other search params (like ?preset=…) to
 *  reconstruct the originating view. */
function decideFromParam(
  from: string,
  search: URLSearchParams,
): BackLink | null {
  if (from === "watchlist") return { href: "/watchlist", label: "관심 종목으로" };
  if (from === "screener") {
    const preset = search.get("preset");
    return {
      href: preset ? `/screener?preset=${encodeURIComponent(preset)}` : "/screener",
      label: "스크리너로",
    };
  }
  return null;
}

export function decideBackLink(
  referer: string | null | undefined,
  searchParams?: URLSearchParams | Record<string, string | undefined>,
): BackLink {
  // 1) Explicit ?from= param (preferred — survives Next.js navigation).
  if (searchParams) {
    const sp =
      searchParams instanceof URLSearchParams
        ? searchParams
        : new URLSearchParams(
            Object.fromEntries(
              Object.entries(searchParams).filter(
                ([, v]) => v != null,
              ) as [string, string][],
            ),
          );
    const from = sp.get("from");
    if (from) {
      const picked = decideFromParam(from, sp);
      if (picked) return picked;
    }
  }

  // 2) Fallback — Referer header.
  if (!referer) return DEFAULT_BACK;
  try {
    const url = new URL(referer);
    const path = url.pathname;
    for (const { prefix, back } of PATH_RULES) {
      const matches =
        path === prefix ||
        path.startsWith(prefix + "/") ||
        path.startsWith(prefix + "?");
      if (matches) {
        // Preserve search params so the user lands back on the exact
        // view they were on (e.g. /screener?preset=value-deep).
        const query = url.search ?? "";
        return query
          ? { href: `${back.href}${query}`, label: back.label }
          : back;
      }
    }
  } catch {
    /* malformed Referer header — treat as no info */
  }
  return DEFAULT_BACK;
}
