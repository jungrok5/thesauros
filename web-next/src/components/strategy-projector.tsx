"use client";

import { useMemo, useState } from "react";

/**
 * "이대로 유지하면 N년 후 얼마" projection panel.
 *
 * Compares 책 전략 (no-SL / max=50 / 24w / top-5 / FULL 2701-ticker
 * universe) against passive alternatives using point-estimate CAGRs
 * from the 17-year backtest.
 *
 * CAGR sources (universe-honest, 2026-05-26 re-sweep w/ book-spirit reform):
 *   - 책 (이상):  14.9% — full universe no-SL/max=50 (sweep_all_24w)
 *   - 책 (보수): ~11.5% — assume 3.4%p cost drag (slip 0.2~0.4%)
 *   - KOSPI BH:  11.48% — metrics.kospi_ann_ret_pct (alpha-beta calc base)
 *   - 정기예금:  3.0%  — Q1 2026 평균
 *   - 채권:      4.5%  — 우량 회사채 평균
 *
 * ⚠️ Honest revision (2026-05-24): previously claimed 27%/21.8% based
 * on 100-tic seed=42 sample bias. Universe verification showed REAL
 * alpha is only +1.91%/y over KOSPI, not +15-19%/y.
 */

const STRATEGIES = [
  {
    key: "book_ideal",
    label: "책 전략 (이상적)",
    cagr: 0.149,
    hint: "no-SL / max=50 / 24w / top-5 — 2701-ticker universe, 슬리피지 0",
    accent: "text-emerald-600 dark:text-emerald-400 font-semibold",
  },
  {
    key: "book_real",
    label: "책 전략 (현실 비용)",
    cagr: 0.115,
    hint: "+거래 비용 0.2~0.4% 슬리피지 가정 (-3~4%p 차감)",
    accent: "text-emerald-700 dark:text-emerald-300 font-semibold",
  },
  {
    key: "kospi",
    label: "KOSPI 매수후 보유",
    cagr: 0.115,
    hint: "17년 historic (metrics.kospi_ann_ret_pct)",
    accent: "text-zinc-700 dark:text-zinc-300",
  },
  {
    key: "savings",
    label: "정기예금",
    cagr: 0.030,
    hint: "Q1 2026 평균",
    accent: "text-zinc-700 dark:text-zinc-300",
  },
  {
    key: "bond",
    label: "우량 회사채",
    cagr: 0.045,
    hint: "AA- 5년물 평균",
    accent: "text-zinc-700 dark:text-zinc-300",
  },
] as const;

const KRW_FORMATTER = new Intl.NumberFormat("ko-KR", {
  maximumFractionDigits: 0,
});

function fmtKRW(n: number): string {
  if (n >= 100_000_000) {
    return `${(n / 100_000_000).toFixed(2)}억`;
  }
  if (n >= 10_000_000) {
    return `${(n / 10_000_000).toFixed(2)}천만`;
  }
  if (n >= 10_000) {
    return `${(n / 10_000).toFixed(0)}만`;
  }
  return KRW_FORMATTER.format(n);
}

interface StrategyProjectorProps {
  /** Default initial amount (만원). Defaults to 1000 (= 1천만). */
  defaultAmountManwon?: number;
  /** Default holding years. */
  defaultYears?: number;
  /** Optional title override (e.g. "이 종목 유지 시 vs 다른 전략"). */
  title?: string;
}

export function StrategyProjector({
  defaultAmountManwon = 1000,
  defaultYears = 10,
  title = "이대로 유지하면 N년 후",
}: StrategyProjectorProps) {
  const [amountManwon, setAmountManwon] = useState(defaultAmountManwon);
  const [years, setYears] = useState(defaultYears);

  const principalKRW = amountManwon * 10_000;

  const rows = useMemo(
    () =>
      STRATEGIES.map((s) => {
        const final = principalKRW * Math.pow(1 + s.cagr, years);
        const gain = final - principalKRW;
        const multiple = final / principalKRW;
        return { ...s, final, gain, multiple };
      }).sort((a, b) => b.final - a.final),
    [principalKRW, years],
  );

  const topGain = rows[0].gain;
  const kospi = rows.find((r) => r.key === "kospi");

  return (
    <section className="rounded-lg border border-border bg-card p-4 space-y-4">
      <header className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-base font-semibold tracking-tight">{title}</h3>
        <span className="text-xs text-muted-foreground">
          17년 backtest 기반 단순 CAGR 환산. 미래 보장 아님.
        </span>
      </header>

      <div className="grid grid-cols-2 gap-3">
        <label className="text-sm space-y-1">
          <span className="text-muted-foreground">원금</span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              inputMode="numeric"
              min={10}
              max={1_000_000}
              step={100}
              value={amountManwon}
              onChange={(e) => setAmountManwon(Math.max(10, Number(e.target.value) || 0))}
              className="w-28 rounded-md border border-border bg-background px-2 py-1 text-right tabular-nums"
            />
            <span className="text-xs text-muted-foreground">만원</span>
          </div>
        </label>
        <label className="text-sm space-y-1">
          <span className="text-muted-foreground">기간</span>
          <div className="flex items-center gap-2">
            <input
              type="range"
              min={1}
              max={30}
              step={1}
              value={years}
              onChange={(e) => setYears(Number(e.target.value))}
              className="flex-1"
            />
            <span className="w-12 text-right tabular-nums">
              {years}년
            </span>
          </div>
        </label>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs uppercase text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left py-1.5 pr-2">전략</th>
              <th className="text-right py-1.5 px-2">CAGR</th>
              <th className="text-right py-1.5 px-2">예상 평가액</th>
              <th className="text-right py-1.5 px-2">수익</th>
              <th className="text-right py-1.5 pl-2">배수</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isTop = r.gain === topGain;
              return (
                <tr key={r.key} className="border-b border-border/50 last:border-0">
                  <td className="py-2 pr-2">
                    <div className={r.accent}>{r.label}</div>
                    <div className="text-xs text-muted-foreground">{r.hint}</div>
                  </td>
                  <td className="text-right px-2 text-muted-foreground">
                    {(r.cagr * 100).toFixed(1)}%
                  </td>
                  <td className={`text-right px-2 ${isTop ? "font-semibold" : ""}`}>
                    {fmtKRW(r.final)}
                  </td>
                  <td className={`text-right px-2 ${isTop ? "font-semibold text-emerald-600 dark:text-emerald-400" : ""}`}>
                    {r.gain >= 0 ? "+" : ""}{fmtKRW(r.gain)}
                  </td>
                  <td className={`text-right pl-2 ${isTop ? "font-semibold" : ""}`}>
                    {r.multiple.toFixed(2)}x
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {kospi && (
        <div className="text-xs text-muted-foreground leading-relaxed">
          책 전략 (현실 비용 ~11.5%/년) 으로 {amountManwon.toLocaleString()}만원을
          {" "}{years}년 유지하면 KOSPI BH 대비 차이는 점점 벌어집니다 — 실제
          outperformance 는 17년 데이터로 검증 시 <strong>+3.4%p/year</strong>{" "}
          수준 (full 2701-ticker universe, 2026-05-26 책 정신 reform 후 re-sweep).
          100-ticker random sample 결과 (+27%/y) 는 sample bias 로 over-estimate
          임을 universe 검증으로 확인 (2026-05-24). 책 전략의 가치는 절대 return
          보다 균형 잡힌 risk-adjusted profile — Sharpe 0.66, Sortino 0.77,
          DD 51.5% (KOSPI BH 대비 DD ↓).
        </div>
      )}
    </section>
  );
}
