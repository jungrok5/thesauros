/**
 * Vercel Cron → GitHub Actions dispatch for weekly-scan.yml.
 *
 * 금요일 08:00 UTC = 17:00 KST 만 실행. KRX 주봉 종가 (15:30) 후
 * FDR/Naver 데이터 publish 안정화 후 분석 트리거.
 *
 * 책 정신 (2부 3장): 매매 결정은 주봉 종가 후 1회. enter / exit /
 * pyramid 알림이 여기서 발사.
 */
import { NextResponse } from "next/server";
import { verifyCronAuth, dispatchWorkflow } from "../_dispatch";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const unauth = verifyCronAuth(req);
  if (unauth) return unauth;
  return dispatchWorkflow("weekly-scan.yml");
}
