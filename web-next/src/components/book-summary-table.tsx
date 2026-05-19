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

function rallyLine(r: AnalysisResult): string {
  const parts: string[] = [];
  if (typeof r.rally_8w_pct === "number") {
    const sign = r.rally_8w_pct >= 0 ? "+" : "";
    parts.push(`8주 ${sign}${(r.rally_8w_pct * 100).toFixed(0)}%`);
  }
  if (typeof r.position_in_52w === "number") {
    parts.push(`52주 위치 ${(r.position_in_52w * 100).toFixed(0)}%`);
  }
  const w = r.trend.weekly;
  if (w?.ma_240 != null && w.ma_240 > 0) {
    const dist = ((r.last_close / w.ma_240) - 1) * 100;
    const sign = dist >= 0 ? "+" : "";
    parts.push(`240MA 대비 ${sign}${dist.toFixed(0)}%`);
  }
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function candleLine(r: AnalysisResult): string {
  const lc = r.last_candle;
  if (!lc) return "—";
  const colorWord = lc.is_bullish ? "양봉" : "음봉";
  const parts = [colorWord, `body ${(lc.body_pct * 100).toFixed(0)}%`];
  if (lc.upper_wick_pct >= 0.20) parts.push(`위꼬리 ${(lc.upper_wick_pct * 100).toFixed(0)}%`);
  if (lc.lower_wick_pct >= 0.20) parts.push(`아랫꼬리 ${(lc.lower_wick_pct * 100).toFixed(0)}%`);
  const tags = (lc.tags ?? []).filter((t) =>
    !["양봉", "음봉"].includes(t),
  );
  if (tags.length > 0) parts.push(tags.join("/"));
  return parts.join(" · ");
}

function volumeLine(r: AnalysisResult): string {
  const vc = r.volume_case;
  if (!vc) return "데이터 부족";
  return `Case ${vc.case} · ${vc.label_kr}`;
}

function quarterLine(r: AnalysisResult): string {
  const zone = r.quarter_zone;
  if (!zone || zone === "n/a") return "장대양봉 catalyst 없음 — 적용 X";
  const labels: Record<string, string> = {
    safe75: "✅ 75% 안전지대 (책: 매집 살아있음 · 추가 매수 OK)",
    warn50: "⚠️ 50~75% 관찰 (안전지대 살짝 이탈)",
    danger25: "🔴 25~50% 매입원가 영역 (적신호)",
    broken: "❌ 25% 절대자리 깨짐 (catalyst 부정 · 매도 자리)",
  };
  return labels[zone] ?? zone;
}

function patternLine(r: AnalysisResult): string {
  const all = r.patterns ?? [];
  const valid = all.filter((p) => p.completed && !p.invalidated);
  const invalidated = all.filter((p) => p.invalidated);

  const parts: string[] = [];
  if (valid.length > 0) {
    const top = [...valid].sort((a, b) => b.confidence - a.confidence).slice(0, 2);
    parts.push(
      top
        .map((p) => {
          const tf = p.timeframe === "monthly" ? "월" : p.timeframe === "weekly" ? "주" : "일";
          return `${p.kind} (${tf}봉, ${(p.confidence * 100).toFixed(0)}%)`;
        })
        .join(" · "),
    );
  }
  if (invalidated.length > 0) {
    parts.push(`⚠ ${invalidated.length}건 무효화됨`);
  }
  if (parts.length === 0) return "감지된 완성 패턴 없음";
  return parts.join(" · ");
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
  const f = Math.round(flow.foreignNet / 1e8);
  const i = Math.round(flow.institutionNet / 1e8);
  const fStr = f === 0 ? "0" : (f > 0 ? `+${f}` : `${f}`);
  const iStr = i === 0 ? "0" : (i > 0 ? `+${i}` : `${i}`);
  return `7일 합산: 외인 ${fStr}억 · 기관 ${iStr}억`;
}

interface Props {
  result: AnalysisResult;
  flow?: FlowSummary | null;
}

export function BookSummaryTable({ result, flow }: Props) {
  const r = result;
  const rows: Array<[string, string | null]> = [
    ["추세",          trendLine(r)],
    ["상승률",        rallyLine(r)],
    ["마지막 캔들",   candleLine(r)],
    ["거래량",        volumeLine(r)],
    ["패턴",          patternLine(r)],
    ["4등분선",       quarterLine(r)],
    ["손절선",        stopLine(r)],
    ["다음 결정",     nextDecisionLine()],
    ["외인+기관",     flowLine(flow)],
  ].filter((row): row is [string, string] => row[1] != null && row[1] !== "—");

  return (
    <section className="rounded-lg border border-border bg-card overflow-hidden">
      <header className="px-4 py-2.5 border-b border-border bg-muted/30">
        <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
          📊 책 정신 정리표 — 매매 결정 차원
        </h2>
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
