/**
 * /chart-vision — 차트 이미지 자동 분석.
 *
 * 사용자가 모바일 증권 앱에서 차트를 스크린샷으로 캡쳐 → 업로드 →
 * 책 정신 규칙으로 자동 분석 결과 표시. 한국·미국·암호화폐·해외
 * 어떤 차트든 OK.
 *
 * 미국 종목 universe 제거 (P_US, migration 045) 후의 보완 — 사용자가
 * 가지고 있는 어떤 차트도 책 패턴으로 식별 가능.
 *
 * MVP: stateless. 이미지 저장 X (privacy). 결과는 페이지 안에서만 표시,
 * 새로고침하면 사라짐. 분석 이력 + rate limit 은 P_VISION_2.
 */
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowLeft, Camera } from "lucide-react";
import { auth } from "@/auth";
import { ChartVisionClient } from "./client";

export const dynamic = "force-dynamic";

// Defence in depth (회고 #62): sidebar 의 admin gating 외에 페이지 자체도
// admin 만 통과. URL 직접 입력으로 일반 user 가 진입해도 redirect 됨.
// chart-vision route.ts 도 access_status='approved' 검사 (별도 layer).
export default async function ChartVisionPage() {
  const session = await auth();
  const u = session?.user as { role?: string; email?: string } | undefined;
  if (!u?.email) redirect("/login");
  if (u.role !== "admin") redirect("/dashboard");
  return (
    <div className="space-y-6 max-w-3xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Camera className="h-6 w-6" /> 차트 이미지 분석
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          모바일 증권 앱 (증권사 MTS, 트레이딩뷰, Webull 등) 의 차트
          스크린샷을 올리면 책 정신 규칙으로 자동 식별. 한국 종목은 물론
          미국·해외·암호화폐 차트도 가능합니다.
        </p>
      </header>

      <section className="rounded-xl border-2 border-zinc-500/30 bg-zinc-500/5 p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-zinc-700 dark:text-zinc-300">
          💡 책 정신 분석 — 무엇을 식별?
        </div>
        <ul className="text-xs space-y-1 leading-relaxed text-muted-foreground">
          <li className="flex gap-2"><span>·</span><span><strong>패턴 8가지</strong> — 쌍바닥 / 역H&S / 삼중바닥 / 컵핸들 / 쌍천장 / H&S / 삼중천장 / 원형천장</span></li>
          <li className="flex gap-2"><span>·</span><span><strong>이평선</strong> — 240MA 위/아래, 정배열/역배열, 돌반지 (돌파-지지-반등)</span></li>
          <li className="flex gap-2"><span>·</span><span><strong>거래량</strong> — 폭증·감소·분배 의심 (선행성 신호)</span></li>
          <li className="flex gap-2"><span>·</span><span><strong>한 줄 평</strong> + 행동 제안 (점검 / 검토 / 원칙대로)</span></li>
        </ul>
      </section>

      <ChartVisionClient />

      <section className="rounded-lg border border-dashed border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1 leading-relaxed">
        <div className="font-medium text-foreground">⚠️ 사용 시 주의</div>
        <p>
          이 분석은 책 (성승현) 의 규칙을 자동 적용한 보조 도구입니다.
          매매 결정은 본인 책임 — 차트의 마지막 종가 + 시장 상황을
          종합 판단 후 진행하세요. 책 정신: <strong>매매는 안 할수록 좋다</strong>.
        </p>
        <p>
          업로드한 이미지는 분석 후 즉시 폐기 — 서버에 저장하지 않습니다.
        </p>
      </section>
    </div>
  );
}
