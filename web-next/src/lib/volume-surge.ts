/**
 * Pure helpers for /volume-surge — weekly volume vs 8-week-average
 * surge detection + 책 §거래량 12 케이스 단순화 interpretation.
 *
 * Kept apart from page.tsx so the surge math + interpretation table
 * can be tested without spinning Supabase. The page itself does I/O
 * + render, passes raw bars[] in, displays the output.
 */

export type WeekBar = {
  ticker: string;
  bar_date: string;
  close: number;
  volume: number;
};

export type SurgeHit = {
  ticker: string;
  thisWeekVol: number;
  avgVol: number;
  ratio: number;
  thisWeekClose: number;
  prevWeekClose: number;
  priceChangePct: number;
};

const MIN_HISTORY_BARS = 5;
const MIN_PAST_VOL_SAMPLES = 4;
const SURGE_THRESHOLD = 2.0;

export function detectSurges(bars: WeekBar[]): SurgeHit[] {
  const byTicker = new Map<string, WeekBar[]>();
  for (const r of bars) {
    const arr = byTicker.get(r.ticker) ?? [];
    arr.push(r);
    byTicker.set(r.ticker, arr);
  }

  const hits: SurgeHit[] = [];
  for (const [ticker, arr] of byTicker.entries()) {
    if (arr.length < MIN_HISTORY_BARS) continue;
    arr.sort((a, b) => b.bar_date.localeCompare(a.bar_date));
    const thisWeek = arr[0];
    const prevWeek = arr[1];
    const past8 = arr.slice(1, 9);
    const past8Vols = past8
      .map((r) => Number(r.volume ?? 0))
      .filter((v) => v > 0);
    if (past8Vols.length < MIN_PAST_VOL_SAMPLES) continue;
    const avgVol = past8Vols.reduce((a, b) => a + b, 0) / past8Vols.length;
    const thisVol = Number(thisWeek.volume ?? 0);
    if (avgVol === 0 || thisVol === 0) continue;
    const ratio = thisVol / avgVol;
    if (ratio < SURGE_THRESHOLD) continue;
    const thisClose = Number(thisWeek.close);
    const prevClose = Number(prevWeek?.close ?? 0);
    const priceChangePct = prevClose > 0 ? (thisClose / prevClose - 1) * 100 : 0;
    hits.push({
      ticker,
      thisWeekVol: thisVol,
      avgVol,
      ratio,
      thisWeekClose: thisClose,
      prevWeekClose: prevClose,
      priceChangePct,
    });
  }
  hits.sort((a, b) => b.ratio - a.ratio);
  return hits;
}

export type SurgeInterpretation = {
  /** Bucket label — UI uses this verbatim. */
  label:
    | "🟢 강한 매집"
    | "🟡 매수 우위"
    | "🔴 강한 매도"
    | "🟠 매도 우위"
    | "🟤 횡보 + 폭증";
  /** Tailwind classes for the row's emphasis. */
  tone: string;
  /** Plain-Korean action guidance. */
  action: string;
};

const PRICE_MOVE_THRESHOLD = 1.5;
const STRONG_SURGE = 3;

export function interpretSurge(h: SurgeHit): SurgeInterpretation {
  const up = h.priceChangePct > PRICE_MOVE_THRESHOLD;
  const down = h.priceChangePct < -PRICE_MOVE_THRESHOLD;
  if (up && h.ratio >= STRONG_SURGE) {
    return {
      label: "🟢 강한 매집",
      tone: "text-rose-700 dark:text-rose-300",
      action:
        "큰 손이 매수 + 가격 동반 상승 = 책 §매수 진입 자리 후보. " +
        "단, 단기 +30% 후 폭증이면 stretch — 추격 매수 X. 차트 정배열 확인 필수.",
    };
  }
  if (up) {
    return {
      label: "🟡 매수 우위",
      tone: "text-amber-700 dark:text-amber-300",
      action:
        "거래량 ↑ + 가격 ↑ 약한 동반. 추세 전환 가능성 — 차트 + 외인 매수 동반이면 매수 검토.",
    };
  }
  if (down && h.ratio >= STRONG_SURGE) {
    return {
      label: "🔴 강한 매도",
      tone: "text-sky-700 dark:text-sky-300",
      action:
        "거래량 폭증 + 가격 ↓ = 큰 손 이탈. 보유 중이면 손절가 즉시 점검, " +
        "신규 매수 X (떨어지는 칼날).",
    };
  }
  if (down) {
    return {
      label: "🟠 매도 우위",
      tone: "text-sky-700 dark:text-sky-300",
      action: "거래량 ↑ + 가격 ↓ 약한 동반. 추세 약화 가능. 보유 중이면 모니터.",
    };
  }
  return {
    label: "🟤 횡보 + 폭증",
    tone: "text-muted-foreground",
    action:
      "거래량만 ↑ + 가격 변화 X = 방향 미정. \"폭풍 전 고요\" 또는 \"의미 없는 회전\" — " +
      "다음 주 가격으로 방향 판단.",
  };
}

export function fmtVol(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(1)}억`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}만`;
  return v.toLocaleString("ko-KR");
}
