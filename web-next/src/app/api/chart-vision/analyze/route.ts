/**
 * POST /api/chart-vision/analyze
 *
 * 사용자가 모바일 증권 앱에서 캡쳐한 차트 이미지를 업로드 → Anthropic
 * Claude Vision API → 책 정신 규칙으로 분석한 JSON 결과 반환.
 *
 * 책 정신 (P_VISION):
 *   - 한국·미국·암호화폐·해외 어떤 차트든 OK (universe 제약 X)
 *   - 책 패턴 (쌍바닥·240MA·포킹·돌반지) + 추세 + 거래량 자동 식별
 *   - 추측 금지, hype 단어 금지, 점검/검토/원칙대로 톤
 *
 * Auth: 로그인 + access_status='approved' user 만. 이미지 저장 X
 * (privacy + storage). 분석 결과만 즉시 반환.
 *
 * Request: multipart/form-data with file=<image>
 * Response: { ok: true, result: {...JSON...} } 또는 { ok: false, error: "..." }
 *
 * MVP — rate limit + 이력 저장은 P_VISION_2 에서.
 */
import { NextRequest, NextResponse } from "next/server";
import Anthropic from "@anthropic-ai/sdk";
import { auth } from "@/auth";
import {
  CHART_VISION_SYSTEM_PROMPT,
  CHART_VISION_USER_PROMPT,
} from "@/lib/chart-vision-prompt";
import { checkAndRecord } from "@/lib/chart-vision-rate-limit";

export const dynamic = "force-dynamic";
// Vision API 보통 5-15s. 30s ceiling: Vercel Hobby 10s 초과 / Pro 60s
// 호환. Vision call timeout (현재 Anthropic SDK default 10min) 를
// 우리 함수 시간보다 짧게 둘 필요는 없음 — Vercel 가 timeout 시키면
// 그 자체로 502 가 적절.
export const maxDuration = 30;

const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const MAX_BYTES = 10 * 1024 * 1024;   // 10 MB — Anthropic vision cap.

export async function POST(req: NextRequest) {
  // ── 1. 인증 ───────────────────────────────────────────────────────
  const session = await auth();
  const user = session?.user as
    | { id?: string; email?: string; access_status?: string }
    | undefined;
  if (!user?.email) {
    return NextResponse.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }
  if (user.access_status !== "approved") {
    return NextResponse.json(
      { ok: false, error: "access pending — 관리자 승인 후 사용 가능합니다" },
      { status: 403 },
    );
  }

  // ── 1b. Rate limit (회고 #28/#29) ─────────────────────────────────
  // 비용 + Anthropic rate cap 보호. user id (없으면 email) 기반 sliding
  // window. 5/분, 30/시, 200/일 — 사용자의 정상 사용 (분당 1-2 차트) 보다
  // 한참 위, 자동화 스크립트 abuse 직전에서 차단.
  const limitKey = user.id ?? user.email;
  const limit = checkAndRecord(limitKey);
  if (!limit.ok) {
    return NextResponse.json(
      {
        ok: false,
        error: `Rate limit 초과 (${limit.window}). ${limit.retryAfterSec}초 후 재시도.`,
        retry_after_sec: limit.retryAfterSec,
      },
      { status: 429, headers: { "Retry-After": String(limit.retryAfterSec) } },
    );
  }

  // ── 2. API key ─────────────────────────────────────────────────────
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    console.error("[chart-vision] ANTHROPIC_API_KEY missing");
    return NextResponse.json(
      { ok: false, error: "Vision API 미설정 — 관리자 문의" },
      { status: 500 },
    );
  }

  // ── 3. 이미지 파싱 ──────────────────────────────────────────────────
  let file: File | null = null;
  try {
    const form = await req.formData();
    const raw = form.get("file");
    if (raw instanceof File) file = raw;
  } catch {
    return NextResponse.json(
      { ok: false, error: "multipart/form-data 파싱 실패" },
      { status: 400 },
    );
  }
  if (!file) {
    return NextResponse.json(
      { ok: false, error: "file 필드가 없습니다" },
      { status: 400 },
    );
  }
  if (!ALLOWED_TYPES.has(file.type)) {
    return NextResponse.json(
      {
        ok: false,
        error: `지원하지 않는 형식: ${file.type}. PNG/JPEG/WebP/GIF 만 가능.`,
      },
      { status: 415 },
    );
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json(
      {
        ok: false,
        error: `파일 크기 ${(file.size / 1024 / 1024).toFixed(1)}MB — 10MB 초과`,
      },
      { status: 413 },
    );
  }

  // ── 4. Base64 인코딩 (Anthropic SDK 가 요구) ───────────────────────
  const bytes = new Uint8Array(await file.arrayBuffer());
  const b64 = Buffer.from(bytes).toString("base64");

  // ── 5. Claude Vision 호출 ──────────────────────────────────────────
  const client = new Anthropic({ apiKey });
  let raw: string;
  try {
    const msg = await client.messages.create({
      model: "claude-sonnet-4-5",   // cost-effective vision model
      max_tokens: 1024,
      system: CHART_VISION_SYSTEM_PROMPT,
      messages: [
        {
          role: "user",
          content: [
            {
              type: "image",
              source: {
                type: "base64",
                media_type: file.type as
                  | "image/png"
                  | "image/jpeg"
                  | "image/webp"
                  | "image/gif",
                data: b64,
              },
            },
            { type: "text", text: CHART_VISION_USER_PROMPT },
          ],
        },
      ],
    });
    // Concat all text blocks (vision response usually has one).
    raw = msg.content
      .filter((b) => b.type === "text")
      .map((b) => ("text" in b ? b.text : ""))
      .join("\n");
  } catch (e) {
    console.error("[chart-vision] anthropic call failed:", e);
    return NextResponse.json(
      {
        ok: false,
        error: "분석 API 호출 실패 — 잠시 후 다시 시도",
        detail: String(e).slice(0, 200),
      },
      { status: 502 },
    );
  }

  // ── 6. JSON 파싱 ───────────────────────────────────────────────────
  // Model is asked to return JSON only, but be tolerant of code-fences.
  const cleaned = raw
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/```\s*$/i, "")
    .trim();
  let parsed: unknown;
  try {
    parsed = JSON.parse(cleaned);
  } catch {
    // Fall back to returning raw — UI can show the unstructured text
    // so the user isn't blocked when the model deviates from JSON.
    return NextResponse.json({ ok: true, result: { raw } });
  }

  return NextResponse.json({ ok: true, result: parsed });
}
