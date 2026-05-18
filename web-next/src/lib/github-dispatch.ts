/**
 * Fire a GitHub Actions workflow_dispatch event. Used to give users
 * an "instant analysis" experience when they add a ticker to their
 * watchlist — the nightly cron would otherwise be the only path and
 * could be 24h away.
 *
 * Requires a fine-grained PAT with `Contents:read` + `Actions:write`
 * scope for the repo, set as `GITHUB_DISPATCH_TOKEN` on Vercel
 * (and locally in .env.local for development).
 *
 * Fire-and-forget: returns true on enqueue, false on any failure.
 * Callers MUST NOT block their response on this.
 */
const OWNER = "jungrok5";
const REPO = "thesauros";

export async function dispatchAnalyzeTicker(ticker: string): Promise<boolean> {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    // Not configured (e.g. local dev without the PAT) — skip silently.
    // The next scheduled cron will still process the ticker.
    return false;
  }
  const url =
    `https://api.github.com/repos/${OWNER}/${REPO}` +
    `/actions/workflows/analyze-ticker.yml/dispatches`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: { ticker },
      }),
    });
    // 204 No Content = enqueued; anything else is unexpected.
    if (res.status !== 204) {
      const text = await res.text().catch(() => "");
      console.warn(
        "analyze-ticker dispatch unexpected status",
        res.status, text.slice(0, 200),
      );
      return false;
    }
    return true;
  } catch (e) {
    console.error("analyze-ticker dispatch failed:", e);
    return false;
  }
}
