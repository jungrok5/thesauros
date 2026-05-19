/**
 * 대시보드 최상단 "오늘의 액션" 카드.
 *
 * 이전 페이지는 결론(시장 레짐 + 매수 우호 라벨)을 3군데에 흩어놨고,
 * "그래서 뭐 해야 하나?"에 대한 동선이 없었다. 이 카드 하나로:
 *   - 한 줄 결론 (책 어조: 매수 우호 / 매도 우호 / 관망)
 *   - 5축 다이얼 점수 (작은 텍스트로 압축)
 *   - 시장 레짐 / VIX / 수익률곡선 / MV=PQ 한 줄
 *   - 다음 액션 버튼 (관심종목 확인 / 종목 검색)
 */
import Link from "next/link";
import { HelpTip } from "@/components/help-tip";
import { ArrowRight } from "lucide-react";

interface Props {
  guidance: string | null;
  regime: string;
  regimeScore: number;
  regimeNote: string;
  dialScores: Record<string, number> | null;
  vixState: string | null;
  yieldCurveInverted: boolean;
  mvPqSignal: string | null;
  updatedAt: string;
}

const REGIME_LABEL: Record<string, string> = {
  CONVICTION: "확신 (버블 경계)",
  HOPE: "희망 — 본격 상승",
  HOPE_DOUBT: "기대반의심반",
  FEAR: "공포 (위기=기회)",
  RISK_OFF: "리스크 회피",
  UNKNOWN: "데이터 부족",
};

const DIAL_LABELS: Record<string, string> = {
  liquidity: "유동성",
  rate: "금리",
  cycle: "경기",
  price: "물가",
  fear: "심리",
};

function toneFor(guidance: string | null) {
  if (!guidance) return "neutral" as const;
  if (/🟢|매수\s*우호|강세|매수\s*검토/.test(guidance)) return "bull" as const;
  if (/🔴|매도|회피|청산/.test(guidance)) return "bear" as const;
  if (/🟡|관찰|관망|조정|주의/.test(guidance)) return "warn" as const;
  return "neutral" as const;
}

function nextActionFor(tone: ReturnType<typeof toneFor>) {
  if (tone === "bull") {
    return {
      primary: { href: "/stocks", label: "종목 검색 — 매수 자리" },
      secondary: { href: "/watchlist", label: "관심 종목 확인" },
      hint: "양호 업종 + 강한 신호 종목 우선. 신규 종목 검색해서 책 정신 정리표 확인.",
    };
  }
  if (tone === "bear") {
    return {
      primary: { href: "/watchlist", label: "보유 종목 청산 검토" },
      secondary: { href: "/stocks", label: "인버스/현금 후보" },
      hint: "신규 매수 보류 — 책: 추세 사망 신호. 보유 종목 10MA 이탈 확인.",
    };
  }
  if (tone === "warn") {
    return {
      primary: { href: "/watchlist", label: "관심 종목 점검" },
      secondary: { href: "/stocks", label: "선별 매수 검색" },
      hint: "기대반의심반 — 선별적 진입 + 변동성 관리. 위꼬리/반전 캔들 주시.",
    };
  }
  return {
    primary: { href: "/stocks", label: "종목 검색" },
    secondary: { href: "/watchlist", label: "관심 종목" },
    hint: "거시 시그널 약함 — 개별 종목 차트 분석 우선.",
  };
}

const TONE_STYLES: Record<string, string> = {
  bull: "border-emerald-500/40 bg-emerald-500/5",
  bear: "border-rose-500/40 bg-rose-500/5",
  warn: "border-amber-500/40 bg-amber-500/5",
  neutral: "border-border bg-card",
};

const TONE_TEXT: Record<string, string> = {
  bull: "text-emerald-700 dark:text-emerald-300",
  bear: "text-rose-700 dark:text-rose-300",
  warn: "text-amber-700 dark:text-amber-300",
  neutral: "text-foreground",
};

export function MarketActionCard({
  guidance, regime, regimeScore, regimeNote, dialScores,
  vixState, yieldCurveInverted, mvPqSignal, updatedAt,
}: Props) {
  const tone = toneFor(guidance);
  const action = nextActionFor(tone);
  const regimeLabel = REGIME_LABEL[regime] ?? regime;
  const total = dialScores
    ? Object.values(dialScores).reduce((s, v) => s + v, 0)
    : null;

  return (
    <section className={`rounded-xl border-2 ${TONE_STYLES[tone]} p-5 space-y-4`}>
      {/* 한 줄 결론 + 다음 액션 버튼 */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
            오늘의 액션
          </div>
          <h2 className={`text-xl font-semibold leading-tight ${TONE_TEXT[tone]}`}>
            {guidance ?? "거시 데이터 갱신 대기 중"}
          </h2>
          <p className="text-sm text-muted-foreground">{action.hint}</p>
        </div>
        <div className="flex flex-col gap-2 items-stretch">
          <Link
            href={action.primary.href}
            className={`inline-flex items-center justify-between gap-2 rounded-md border-2 px-3 py-2 text-sm font-medium transition-colors hover:opacity-90 ${TONE_STYLES[tone]} ${TONE_TEXT[tone]}`}
          >
            {action.primary.label}
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href={action.secondary.href}
            className="inline-flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground hover:bg-muted"
          >
            {action.secondary.label}
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>

      {/* 한 row 매트릭스 — 레짐 / 5축 / VIX / 수익률곡선 / MV=PQ */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-x-4 gap-y-2 text-xs">
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wide">레짐</div>
          <div className="font-medium">
            {regimeLabel}
            <span className="ml-1 font-mono text-muted-foreground">
              {regimeScore >= 0 ? "+" : ""}
              {regimeScore.toFixed(2)}
            </span>
          </div>
        </div>
        {dialScores && Object.entries(DIAL_LABELS).map(([k, label]) => {
          const score = dialScores[k] ?? 0;
          const tone =
            score >= 4 ? "text-emerald-600 dark:text-emerald-400"
            : score >= 3 ? "text-foreground"
            : "text-rose-600 dark:text-rose-400";
          return (
            <div key={k}>
              <div className="text-muted-foreground text-[10px] uppercase tracking-wide">{label}</div>
              <div className={`font-mono ${tone}`}>{score}/5</div>
            </div>
          );
        })}
        {total != null && (
          <div>
            <div className="text-muted-foreground text-[10px] uppercase tracking-wide">5축 합산</div>
            <div className="font-mono">{total}/25</div>
          </div>
        )}
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wide">
            <HelpTip term="vix_state">VIX</HelpTip>
          </div>
          <div>{vixState ?? "—"}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wide">
            <HelpTip term="yield_curve">수익률곡선</HelpTip>
          </div>
          <div className={yieldCurveInverted
            ? "text-rose-600 dark:text-rose-400 font-medium"
            : "text-emerald-600 dark:text-emerald-400"}>
            {yieldCurveInverted ? "역전" : "정상"}
          </div>
        </div>
        <div>
          <div className="text-muted-foreground text-[10px] uppercase tracking-wide">
            <HelpTip term="mv_pq">MV=PQ</HelpTip>
          </div>
          <div className="text-xs">{mvPqSignal ?? "—"}</div>
        </div>
      </div>

      <p className="text-xs text-muted-foreground/80 leading-relaxed">
        {regimeNote}
      </p>
      <p className="text-[10px] text-muted-foreground/60">
        갱신 <span suppressHydrationWarning>{updatedAt}</span>
      </p>
    </section>
  );
}
