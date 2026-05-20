/**
 * Volume Surge Card — stock detail 페이지용.
 *
 * /volume-surge 목록과 같은 메트릭 (this/avg ratio + 가격 변동) +
 * 같은 5-bucket 해석 (강한 매집 / 매수 우위 / 강한 매도 / 매도 우위
 * / 폭풍 전 고요) 을 단일 종목 카드로 표시.
 *
 * ratio < 1.5 면 평이한 거래량 — "정상" 라벨 + 톤다운. 단지 데이터
 * 노출용이라 사용자가 종목 거래량 상태를 즉시 인지.
 */
import { interpretSurge } from "@/lib/volume-surge";
import type { VolumeSurgeRow } from "@/lib/stock-context";

function fmtVol(v: number): string {
  if (v >= 1e8) return `${(v / 1e8).toFixed(1)}억`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}만`;
  return v.toLocaleString("ko-KR");
}

export function VolumeSurgeCard({ surge }: { surge: VolumeSurgeRow | null }) {
  if (!surge || !Number.isFinite(surge.ratio) || surge.ratio <= 0) return null;

  // Reuse the same interpretation as /volume-surge — 5 buckets.
  const interp = interpretSurge({
    ticker: "",
    thisWeekVol: surge.this_week_vol,
    avgVol: surge.avg_vol,
    ratio: surge.ratio,
    thisWeekClose: surge.this_week_close,
    prevWeekClose: surge.prev_week_close,
    priceChangePct: surge.price_change_pct,
  });

  // Below the 2× surge threshold = "정상 거래량". Override label so the
  // card communicates clearly without faking a signal.
  const isNormal = surge.ratio < 2.0;
  const label = isNormal ? "🟤 정상 거래량" : interp.label;
  const action = isNormal
    ? "이번 주 거래량이 평균 대비 2배 미만 — 큰 신호 없음. 평소 흐름 유지."
    : interp.action;

  // Border tone matches /volume-surge interpretation tones.
  const borderCls = isNormal
    ? "border-border bg-card"
    : interp.label.startsWith("🟢") || interp.label.startsWith("🟡")
      ? "border-amber-500/40 bg-amber-500/5"
      : interp.label.startsWith("🔴") || interp.label.startsWith("🟠")
        ? "border-sky-500/40 bg-sky-500/5"
        : "border-zinc-500/30 bg-zinc-500/5";

  return (
    <section className={`rounded-xl border-2 ${borderCls} p-4 space-y-3`}>
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-semibold tracking-tight">
          📊 이번주 거래량 신호
        </h3>
        <span className="text-xs font-medium">{label}</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Tile
          label="이번주 거래량"
          value={fmtVol(surge.this_week_vol)}
        />
        <Tile
          label="직전 8주 평균"
          value={fmtVol(surge.avg_vol)}
          hint={surge.sample_n < 8 ? `${surge.sample_n}주 샘플` : undefined}
        />
        <Tile
          label="배수 (ratio)"
          value={`${surge.ratio.toFixed(1)}x`}
          tone={
            surge.ratio >= 3 ? "warn" :
            surge.ratio >= 2 ? "neutral" :
            undefined
          }
        />
        <Tile
          label="가격 변동 (주)"
          value={`${surge.price_change_pct >= 0 ? "+" : ""}${surge.price_change_pct.toFixed(1)}%`}
          tone={
            surge.price_change_pct >= 1.5 ? "good" :
            surge.price_change_pct <= -1.5 ? "bad" :
            undefined
          }
        />
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">💡 {action}</p>
    </section>
  );
}

function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "good" | "bad" | "warn" | "neutral";
}) {
  const cls =
    tone === "good"
      ? "text-emerald-700 dark:text-emerald-300"
      : tone === "bad"
        ? "text-rose-700 dark:text-rose-300"
        : tone === "warn"
          ? "text-amber-700 dark:text-amber-300"
          : tone === "neutral"
            ? "text-sky-700 dark:text-sky-300"
            : "text-foreground";
  return (
    <div className="rounded-md bg-background/50 p-2.5 space-y-0.5">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm font-mono ${cls}`}>{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  );
}
