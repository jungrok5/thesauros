/**
 * 책 정신 정리표 — 매매 결정에 직접 닿는 차원으로 정보 집약.
 *
 * 시간프레임 매트릭스 (월/주/일)가 아니라, 사용자가 manual로 분석할 때
 * 머릿속에서 거치는 의사결정 차원을 그대로 나열:
 *
 *   추세       월봉/주봉 강세 · 10MA 위치
 *   상승률      8주 +X%, 52w 위치 Y%, 240MA 거리
 *   거래량      Case N · 라벨
 *   마지막 캔들  음봉/양봉 + body + 꼬리
 *   패턴        완성/무효/없음
 *   4등분선     safe75 / warn50 / danger25 / broken
 *   손절선      주봉 10MA $X
 *   다음 결정   다음 봉 마감 시점
 *   외인+기관   7일 합산
 *
 * BookVerdict가 narrative로 결론을 내리고, 이 표는 그 결론의 근거를
 * 차원별로 분리해 보여준다. 표 자체로 결론을 내리진 않음 (한 줄 평이
 * 결론 담당).
 */
import type { AnalysisResult } from "@/lib/types/analysis";
import type { FlowSummary } from "@/components/investor-flow-chip";
import { formatNumber, cn } from "@/lib/utils";
import { HelpTip } from "@/components/help-tip";
import type { ReactNode } from "react";

// Helper: which glossary term a volume case number maps to.
function volumeCaseTerm(caseNo: number): string {
  if (caseNo >= 0 && caseNo <= 12) return `volume_case_${caseNo}`;
  return "volume_case_generic";
}

function quarterTerm(zone: string): string | undefined {
  return {
    safe75: "quarter_safe75",
    warn50: "quarter_warn50",
    danger25: "quarter_danger25",
    broken: "quarter_broken",
  }[zone];
}

function priceFmt(v: number | null | undefined, ticker: string): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const isUS = !/\.KS$|\.KQ$/.test(ticker);
  if (isUS) return `$${v.toFixed(2)}`;
  return formatNumber(v);
}

function trendLine(r: AnalysisResult): string {
  const m = r.trend.monthly;
  const w = r.trend.weekly;
  const mLabel = m?.label ?? "—";
  const wLabel = w?.label ?? "—";
  const wMA10 = w?.ma_10 != null
    ? `주봉 10MA ${priceFmt(w.ma_10, r.ticker)} ${w.above_ma_10 ? "▲" : "▼"}`
    : "";
  return [`월봉 ${mLabel} · 주봉 ${wLabel}`, wMA10].filter(Boolean).join(" · ");
}

function rallyLine(r: AnalysisResult): ReactNode {
  const parts: ReactNode[] = [];
  if (typeof r.rally_8w_pct === "number") {
    const sign = r.rally_8w_pct >= 0 ? "+" : "";
    parts.push(
      <HelpTip key="r" term="rally_8w">
        {`8주 ${sign}${(r.rally_8w_pct * 100).toFixed(0)}%`}
      </HelpTip>,
    );
  }
  if (typeof r.position_in_52w === "number") {
    parts.push(
      <HelpTip key="p" term="pos_52w">
        {`52주 위치 ${(r.position_in_52w * 100).toFixed(0)}%`}
      </HelpTip>,
    );
  }
  const w = r.trend.weekly;
  if (w?.ma_240 != null && w.ma_240 > 0) {
    const dist = ((r.last_close / w.ma_240) - 1) * 100;
    const sign = dist >= 0 ? "+" : "";
    parts.push(
      <HelpTip key="m" term="ma_240_distance">
        {`240MA 대비 ${sign}${dist.toFixed(0)}%`}
      </HelpTip>,
    );
  }
  if (parts.length === 0) return "—";
  return (
    <>
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {p}
        </span>
      ))}
    </>
  );
}

const CANDLE_TAG_TERM: Record<string, string> = {
  "장대양봉": "jangdae_yangbong",
  "장대음봉": "jangdae_eumbong",
  "구라캔들": "gura_candle",
  "양팔봉": "yangpalbong",
  "은둔형장대양봉": "hidden_jangdae",
  "주고받고": "jugobatgo_candle",
  "눈썹캔들": "nunsseop_candle",
};

function candleLine(r: AnalysisResult): ReactNode {
  const lc = r.last_candle;
  if (!lc) return "—";
  const colorTerm = lc.is_bullish ? "yangbong" : "eumbong";
  const colorWord = lc.is_bullish ? "양봉" : "음봉";
  const tags = (lc.tags ?? []).filter((t) => !["양봉", "음봉"].includes(t));
  return (
    <>
      <HelpTip term={colorTerm}>{colorWord}</HelpTip>
      {" · "}
      <span>body {(lc.body_pct * 100).toFixed(0)}%</span>
      {lc.upper_wick_pct >= 0.20 && (
        <> · <span>위꼬리 {(lc.upper_wick_pct * 100).toFixed(0)}%</span></>
      )}
      {lc.lower_wick_pct >= 0.20 && (
        <> · <span>아랫꼬리 {(lc.lower_wick_pct * 100).toFixed(0)}%</span></>
      )}
      {tags.map((t) => {
        const term = CANDLE_TAG_TERM[t];
        return (
          <span key={t}>
            {" · "}
            {term ? <HelpTip term={term}>{t}</HelpTip> : t}
          </span>
        );
      })}
    </>
  );
}

function volumeLine(r: AnalysisResult): ReactNode {
  const vc = r.volume_case;
  if (!vc) return "데이터 부족";
  return (
    <HelpTip term={volumeCaseTerm(vc.case)}>
      Case {vc.case} · {vc.label_kr}
    </HelpTip>
  );
}

function quarterLine(r: AnalysisResult): ReactNode {
  const zone = r.quarter_zone;
  if (!zone || zone === "n/a") {
    return (
      <HelpTip term="catalyst_candle">
        장대양봉 catalyst 없음 — 적용 X
      </HelpTip>
    );
  }
  const labels: Record<string, string> = {
    safe75: "✅ 75% 안전지대 (책: 매집 살아있음 · 추가 매수 OK)",
    warn50: "⚠️ 50~75% 관찰 (안전지대 살짝 이탈)",
    danger25: "🔴 25~50% 매입원가 영역 (적신호)",
    broken: "❌ 25% 절대자리 깨짐 (catalyst 부정 · 매도 자리)",
  };
  const term = quarterTerm(zone);
  const content = labels[zone] ?? zone;
  return term ? <HelpTip term={term}>{content}</HelpTip> : <>{content}</>;
}

function indicatorsLine(r: AnalysisResult): ReactNode | null {
  const ind = r.indicators;
  if (!ind) return null;
  const parts: ReactNode[] = [];
  if (ind.rsi != null && ind.rsi_interpretation) {
    parts.push(
      <HelpTip key="rsi" term="rsi">
        {ind.rsi_interpretation}
      </HelpTip>,
    );
  }
  if (ind.macd != null && ind.macd_interpretation) {
    parts.push(
      <HelpTip key="macd" term="macd">
        {ind.macd_interpretation}
      </HelpTip>,
    );
  }
  if (parts.length === 0) return null;
  return (
    <span className="space-y-1 block">
      {parts.map((p, i) => (
        <span key={i} className="block">
          {p}
        </span>
      ))}
    </span>
  );
}

function patternLine(r: AnalysisResult): ReactNode {
  const all = r.patterns ?? [];
  const valid = all.filter((p) => p.completed && !p.invalidated);
  const invalidated = all.filter((p) => p.invalidated);

  const parts: ReactNode[] = [];
  if (valid.length > 0) {
    const top = [...valid].sort((a, b) => b.confidence - a.confidence).slice(0, 2);
    parts.push(
      ...top.map((p, idx) => {
        const tf = p.timeframe === "monthly" ? "월" : p.timeframe === "weekly" ? "주" : "일";
        return (
          <span key={`v${idx}`}>
            {idx > 0 && " · "}
            {p.kind} ({tf}봉, {(p.confidence * 100).toFixed(0)}%)
          </span>
        );
      }),
    );
  }
  if (invalidated.length > 0) {
    parts.push(
      <span key="inv">
        {parts.length > 0 && " · "}
        <HelpTip term="pattern_invalidation">
          ⚠ {invalidated.length}건 무효화됨
        </HelpTip>
      </span>,
    );
  }
  if (parts.length === 0) return "감지된 완성 패턴 없음";
  return <>{parts}</>;
}

function stopLine(r: AnalysisResult): string {
  const w = r.trend.weekly;
  if (w?.ma_10 != null) {
    return `주봉 10MA ${priceFmt(w.ma_10, r.ticker)} 이탈 시 (책: 추세 사망 라인)`;
  }
  if (r.entry_plan?.stop != null) {
    return `${priceFmt(r.entry_plan.stop, r.ticker)} (${r.entry_plan.based_on})`;
  }
  return "—";
}

function nextDecisionLine(): string {
  return "이번 주 금요일 종가 (KST 15:30) — 책: 주봉 종가매매 모드";
}

function flowLine(flow: FlowSummary | null | undefined): string | null {
  if (!flow) return null;
  return `7일 합산: 외인 ${fmtKrw(flow.foreignNet)} · 기관 ${fmtKrw(flow.institutionNet)}`;
}

/** Pick "조원" vs "억원" automatically so 7-day flow on a large-cap
 *  ticker doesn't read as "-30345억" (hard to parse at a glance).
 *  Threshold: ≥ 1조원 (1 trillion KRW) → 조 단위 with 1 decimal.
 *  Below that → 억 단위, integer. (2026-05-26 audit pass.) */
function fmtKrw(krw: number): string {
  const ABS = Math.abs(krw);
  if (ABS >= 1e12) {
    const trillions = krw / 1e12;
    const sign = trillions > 0 ? "+" : "";
    return `${sign}${trillions.toFixed(1)}조`;
  }
  const eok = Math.round(krw / 1e8);
  if (eok === 0) return "0";
  const sign = eok > 0 ? "+" : "";
  return `${sign}${eok.toLocaleString("ko-KR")}억`;
}

interface Props {
  result: AnalysisResult;
  flow?: FlowSummary | null;
}

export function BookSummaryTable({ result, flow }: Props) {
  const r = result;
  const rowsRaw: Array<[string, ReactNode | null]> = [
    ["추세",          trendLine(r)],
    ["상승률",        rallyLine(r)],
    ["마지막 캔들",   candleLine(r)],
    ["거래량",        volumeLine(r)],
    ["패턴",          patternLine(r)],
    ["4등분선",       quarterLine(r)],
    ["RSI / MACD",   indicatorsLine(r)],
    ["손절선",        stopLine(r)],
    ["다음 결정",     nextDecisionLine()],
    ["외인+기관",     flowLine(flow)],
  ];
  // Filter out null + "—" empty rows.
  const rows = rowsRaw.filter(([, v]) => {
    if (v == null) return false;
    if (typeof v === "string" && (v === "" || v === "—")) return false;
    return true;
  }) as Array<[string, ReactNode]>;

  return (
    <section className="rounded-lg border border-border bg-card overflow-hidden">
      <header className="px-4 py-2.5 border-b border-border bg-muted/30 space-y-0.5">
        <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
          📊 결정 근거 — 6 차원 상세 (참고)
        </h2>
        {/* 2026-05-26 site review: 이전 이름 "책 정신 정리표 — 매매 결정
            차원" 이 결론처럼 들려 초보가 위쪽 한 줄 평을 건너뛰고 이 표를
            결론으로 오해. 표는 결론의 근거 raw data — 결론은 위의 한 줄
            평이 함. 라벨 + 안내문으로 명확화. */}
        <p className="text-[11px] text-muted-foreground/80">
          ↑ 위 <strong>한 줄 평</strong>이 결론 · 아래는 차원별 raw 데이터
        </p>
      </header>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([label, value], i) => (
            <tr
              key={label}
              className={cn(
                "border-b border-border last:border-b-0",
                i % 2 === 1 && "bg-muted/10",
              )}
            >
              <td className="px-4 py-2 align-top text-xs uppercase tracking-wide text-muted-foreground w-24 md:w-28">
                {label}
              </td>
              <td className="px-4 py-2 align-top leading-relaxed">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
