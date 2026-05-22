/**
 * Vercel Cron → GitHub Actions dispatch for daily-data.yml.
 *
 * 매일 08:00 UTC = 17:00 KST. KR 종가가 publish 된 후 안정화 시점.
 * 책 정신 (2부 3장) 분리: daily-data 는 데이터 적재 + 이벤트 알림만.
 * 매매 결정 (scan_daily / enter-class telegram) 은 weekly-scan.yml.
 */
import { NextResponse } from "next/server";
import { verifyCronAuth, dispatchWorkflow } from "../_dispatch";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const unauth = verifyCronAuth(req);
  if (unauth) return unauth;
  return dispatchWorkflow("daily-data.yml");
}
