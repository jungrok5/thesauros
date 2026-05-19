/**
 * Decide where a "back" link on a stock-detail-style page should point.
 *
 * Used by /stocks/[ticker] (and any future page that shares the same
 * "user came here from somewhere; show me the way back" pattern). Pure
 * function on Referer so it's trivially testable + so it works inside
 * a server component without grabbing a router.
 *
 * Behavior:
 *   /watchlist*           → "관심 종목으로"
 *   anything else / null  → "종목 검색"
 *
 * We deliberately don't chain history. If the user came
 *   /watchlist → /stocks/AAPL → /stocks/MSFT
 * the Referer on MSFT is /stocks/AAPL, so the back link goes to /stocks
 * (search). That's the right "step out" destination; the user always
 * has the browser back button for true history walking.
 */
export type BackLink = { href: string; label: string };

const DEFAULT_BACK: BackLink = { href: "/stocks", label: "종목 검색" };

export function decideBackLink(referer: string | null | undefined): BackLink {
  if (!referer) return DEFAULT_BACK;
  try {
    const url = new URL(referer);
    const path = url.pathname;
    if (path === "/watchlist" || path.startsWith("/watchlist/")) {
      return { href: "/watchlist", label: "관심 종목으로" };
    }
  } catch {
    /* malformed Referer header — treat as no info */
  }
  return DEFAULT_BACK;
}
