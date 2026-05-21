/**
 * Vercel Cron → GitHub Actions workflow_dispatch trigger for the
 * daily book-rule scan.
 *
 * Why: GitHub Actions `schedule:` cron is best-effort on the free tier
 * and has been observed to silently miss the 17:00 KST run during
 * high-traffic windows (2026-05-21 — Daily Book-Rule Scan didn't fire
 * at all on a Thursday). Vercel Cron runs on independent infrastructure
 * with ~100% trigger reliability, so we delegate the "when" to Vercel
 * and use GitHub Actions only as the "how" (the actual ingest +
 * analysis runner).
 *
 * Flow:
 *   Vercel Cron (vercel.json) → POST /api/cron/daily-scan with
 *     Authorization: Bearer ${CRON_SECRET} (set automatically by Vercel)
 *   → this route calls the GitHub API workflow_dispatch endpoint
 *   → daily-scan.yml runs the full ingest + analysis + telegram pipeline.
 *
 * Auth: Vercel attaches `Authorization: Bearer ${CRON_SECRET}` to every
 * cron-triggered request. We verify this header before any side effect
 * so an untrusted internet request can't spam our GitHub API quota.
 * CRON_SECRET is a Vercel-system env (generated per project) — no manual
 * setup required beyond enabling Vercel Cron.
 */
import { NextResponse } from "next/server";

const OWNER = "jungrok5";
const REPO = "thesauros";
const WORKFLOW_FILE = "daily-scan.yml";

export const dynamic = "force-dynamic";
// Vercel Cron must be GET (POST is for user-initiated webhooks).
export async function GET(req: Request) {
  // 1) Verify the request is from Vercel Cron, not a stranger.
  const auth = req.headers.get("authorization") ?? "";
  const expected = `Bearer ${process.env.CRON_SECRET ?? ""}`;
  if (!process.env.CRON_SECRET || auth !== expected) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  // 2) Dispatch the daily-scan workflow via GitHub REST API.
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    return NextResponse.json(
      { error: "GITHUB_DISPATCH_TOKEN not configured" },
      { status: 500 },
    );
  }
  const url =
    `https://api.github.com/repos/${OWNER}/${REPO}` +
    `/actions/workflows/${WORKFLOW_FILE}/dispatches`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    if (res.status !== 204) {
      const text = await res.text().catch(() => "");
      return NextResponse.json(
        {
          error: "github dispatch unexpected status",
          status: res.status,
          detail: text.slice(0, 300),
        },
        { status: 502 },
      );
    }
    return NextResponse.json({
      ok: true,
      dispatched_at: new Date().toISOString(),
      workflow: WORKFLOW_FILE,
    });
  } catch (e) {
    return NextResponse.json(
      { error: "dispatch failed", detail: String(e) },
      { status: 502 },
    );
  }
}
