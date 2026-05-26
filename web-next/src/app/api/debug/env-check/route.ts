/**
 * TEMPORARY debug endpoint — diagnoses why /api/cron/daily-data
 * returns 401 after CRON_SECRET was added to Vercel production env.
 *
 * Reports only presence + length (NEVER the secret value itself).
 * Delete this file as soon as the root cause is identified.
 */
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const env = process.env.CRON_SECRET ?? "";
  return NextResponse.json({
    cron_secret_present: !!process.env.CRON_SECRET,
    cron_secret_len: env.length,
    cron_secret_prefix: env.slice(0, 4),
    cron_secret_suffix: env.slice(-4),
    auth_header_present: !!req.headers.get("authorization"),
    auth_header_starts_bearer: auth.startsWith("Bearer "),
    auth_token_len: auth.replace(/^Bearer /, "").length,
    auth_token_prefix: auth.replace(/^Bearer /, "").slice(0, 4),
    auth_token_suffix: auth.replace(/^Bearer /, "").slice(-4),
    node_version: process.version,
    vercel_env: process.env.VERCEL_ENV ?? null,
    vercel_region: process.env.VERCEL_REGION ?? null,
  });
}
