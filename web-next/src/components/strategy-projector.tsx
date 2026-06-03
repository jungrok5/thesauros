"use client";

import { useMemo, useState } from "react";

/**
 * "이대로 유지하면 N년 후 얼마" projection panel.
 *
 * 2026-06-03 — v1.1 survivorship-corrected locked baseline.
 * Universe = 3,465 ticker (KR active 2,599 + FDR delisted 866).
 * Simulator auto-closes positions on delisted_at. Prior v1
 * (CAGR 12.48 / Outperf +0.99) was survivorship-inflated by ~1.3 pp.
 *
 * 2026-06-02/03 사이클: v1.1 위에서 24 ranking-factor (R1-R20: cap_q PIT,
 * sector_cap, momentum, entry-bar quality, US lead-lag, 52w position,
 * Naver 17y 외국인/기관 flow contrarian 등) 모두 5-gate 룰 미달 →
 * v1.1 production locked.
 *
 * Compares 책 전략 (book-faithful v1.1 — 책 신호 + 업종 분산 1/주/업종 +
 * 책 매도룰: 종목별 월봉 10MA / 장대양봉 4등분 25% / 천장 패턴 + 폐지일
 * 자동 청산; no 24w force, no SL, no TP; max=20 / 1억 자본 / 3,465-ticker
 * survivorship-corrected universe) against passive alternatives.
 *
 * CAGR sources (2026-06-03 v1.1 run):
 *   - 책 (이상):  11.19% — full 17.4y in-sample
 *   - 책 (현실):  ~9.5% — assume ~1.7pp slippage drag (0.2%/side ×
 *                          ~4 portfolio rotations/year)
 *   - KOSPI BH:   11.48% — metrics.kospi_ann_ret_pct
 *   - 정기예금:   3.0%   — Q1 2026 평균
 *   - 채권:       4.5%   — 우량 회사채 평균
 *
 * Alpha vs KOSPI: +3.36%/y (β-corrected). Raw outperformance -0.29%/y
 * (KOSPI BH 와 동률) — risk-adjusted 알파만 양수.
 */

const STRATEGIES = [
  {
    key: "book_ideal",
    label: "책 전략 (이상적)",
    cagr: 0.1119,
    hint: "book-faithful v1.1: 책 매수+매도룰 + 폐지일 자동청산, 3,465-ticker survivorship-corrected universe, 슬리피지 0",
    accent: "text-emerald-600 dark:text-emerald-400 font-semibold",
  },
  {
    key: "book_real",
    label: "책 전략 (현실 비용)",
    cagr: 0.095,
    hint: "+슬리피지 0.2%/side × 회전율 보정 (-1.7pp 차감)",
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
          책 전략은 17년 백테스트 기준 KOSPI BH 와 절대 수익률이 거의 동률 (raw
          outperformance <strong>-0.29 pp/y</strong>) — 그러나 market-beta-
          corrected 알파는 <strong>+3.36 pp/y</strong> (β = 0.61 로 KOSPI 변동성의
          약 61% 만 부담). 즉 같은 수익을 더 적은 시장 리스크로 얻음.
          Sharpe 0.43 / Sortino 0.61 / DD 63.1% / 슬리피지 0.
          Universe 3,465 ticker (active 2,599 + delisted 866) — 폐지 시점 자동
          청산으로 survivorship bias 제거. 미래 보장 X.
        </div>
      )}
    </section>
  );
}
