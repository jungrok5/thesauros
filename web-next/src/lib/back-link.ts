/**
 * Decide where a "back" link on a stock-detail-style page should point.
 *
 * Used by /stocks/[ticker] (and any future page that shares the same
 * "user came here from somewhere; show me the way back" pattern). Pure
 * function on Referer so it's trivially testable + so it works inside
 * a server component without grabbing a router.
 *
 * Behavior (first match wins):
 *   /watchlist*       → "관심 종목으로"
 *   /screener*        → "종목 스크리너로"      (preserves ?preset=…)
 *   /flow-ranking*    → "큰손 매매 랭킹으로"
 *   /volume-surge*    → "거래량 폭증 목록으로"
 *   anything else     → "종목 검색"  (default)
 *
 * We deliberately don't chain history. If the user came
 *   /watchlist → /stocks/AAPL → /stocks/MSFT
 * the Referer on MSFT is /stocks/AAPL, so the back link goes to /stocks
 * (search). That's the right "step out" destination; the user always
 * has the browser back button for true history walking.
 */
export type BackLink = { href: string; label: string };

const DEFAULT_BACK: BackLink = { href: "/stocks", label: "종목 검색" };

const RULES: Array<{ prefix: string; back: BackLink }> = [
  { prefix: "/watchlist",     back: { href: "/watchlist",     label: "관심 종목으로" } },
  { prefix: "/screener",      back: { href: "/screener",      label: "종목 스크리너로" } },
  { prefix: "/flow-ranking",  back: { href: "/flow-ranking",  label: "큰손 매매 랭킹으로" } },
  { prefix: "/volume-surge",  back: { href: "/volume-surge",  label: "거래량 폭증 목록으로" } },
];

export function decideBackLink(referer: string | null | undefined): BackLink {
  if (!referer) return DEFAULT_BACK;
  try {
    const url = new URL(referer);
    const path = url.pathname;
    for (const { prefix, back } of RULES) {
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
