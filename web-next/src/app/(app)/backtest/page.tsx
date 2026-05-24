/**
 * /backtest — 책 전략 17년 backtest 자랑 페이지.
 *
 * Loads the precomputed equity curve + summary stats from
 * web-next/public/equity-production.json (built by scripts/
 * build_equity_json.py from data/equity_production.csv).
 *
 * Stats panel = Sprint 1 winning config metrics:
 *   SL=10% / max=8 / 24w hold / top-5 entries — +6380% / Sharpe 0.82.
 *
 * Server component. Loads JSON via fs.readFile (cached per process).
 */
import fs from "node:fs/promises";
import path from "node:path";
import { EquityCurveChart } from "@/components/equity-curve-chart";
import { StrategyProjector } from "@/components/strategy-projector";

interface EquityData {
  config: string;
  start: string;
  end: string;
  initial: number;
  final: number;
  summary: {
    total_return_pct: number;
    annualised_return_pct: number;
    max_drawdown_pct: number;
    sharpe: number;
    sortino: number;
    calmar: number;
    alpha_annual_pct: number;
    beta: number;
    r_squared: number;
    kospi_ann_ret_pct: number;
    outperformance_ann_pct: number;
  };
  weekly: { d: string; e: number }[];
}

let EQUITY_CACHE: EquityData | null = null;

async function loadEquity(): Promise<EquityData | null> {
  if (EQUITY_CACHE) return EQUITY_CACHE;
  try {
    const p = path.join(process.cwd(), "public", "equity-production.json");
    const text = await fs.readFile(p, "utf-8");
    EQUITY_CACHE = JSON.parse(text) as EquityData;
    return EQUITY_CACHE;
  } catch {
    return null;
  }
}

export const dynamic = "force-dynamic";

export default async function BacktestPage() {
  const data = await loadEquity();
  if (!data) {
    return (
      <div className="space-y-6 max-w-5xl">
        <h1 className="text-2xl font-semibold tracking-tight">📊 백테스트</h1>
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm">
          equity-production.json 이 누락되었습니다.
          <code className="ml-1 bg-muted px-1 rounded">
            python scripts/build_equity_json.py
          </code>{" "}
          실행 후 새로고침하세요.
        </div>
      </div>
    );
  }

  const s = data.summary;
  const yearsSpan =
    (new Date(data.end).getTime() - new Date(data.start).getTime()) /
    (365.25 * 86_400_000);

  return (
    <div className="space-y-6 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          📊 책 전략 17년 백테스트
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {data.config} —{" "}
          <span className="font-mono">
            {data.start} → {data.end}
          </span>{" "}
          ({yearsSpan.toFixed(1)}년)
        </p>
      </header>

      {/* Headline numbers */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card label="총 수익률" value={`+${s.total_return_pct.toFixed(0)}%`} accent />
        <Card label="연환산 (CAGR)" value={`+${s.annualised_return_pct.toFixed(1)}%/y`} accent />
        <Card label="Sharpe" value={s.sharpe.toFixed(2)} />
        <Card label="Sortino" value={s.sortino.toFixed(2)} />
        <Card label="Max DD" value={`-${s.max_drawdown_pct.toFixed(1)}%`} negative />
        <Card label="Calmar" value={s.calmar.toFixed(2)} />
        <Card label="Alpha vs KOSPI" value={`+${s.alpha_annual_pct.toFixed(1)}%/y`} accent />
        <Card label="Beta" value={s.beta.toFixed(2)} />
      </section>

      {/* Equity curve */}
      <section className="space-y-3">
        <header className="flex items-baseline justify-between flex-wrap gap-2">
          <h2 className="text-lg font-semibold tracking-tight">평가액 (MTM)</h2>
          <span className="text-sm tabular-nums">
            {(data.initial / 10_000).toLocaleString()}만원 →{" "}
            <strong className="text-emerald-600 dark:text-emerald-400">
              {(data.final / 100_000_000).toFixed(2)}억 (
              {(data.final / data.initial).toFixed(1)}x)
            </strong>
          </span>
        </header>
        <EquityCurveChart
          weekly={data.weekly}
          initial={data.initial}
        />
        <p className="text-xs text-muted-foreground leading-relaxed">
          KOSPI 매수후 보유 (BH) 같은 17년 동안 연 {s.kospi_ann_ret_pct.toFixed(1)}%
          → outperformance <strong>+{s.outperformance_ann_pct.toFixed(1)}%p/y</strong>.
          Beta {s.beta.toFixed(2)} = 시장 변동성의 약 {Math.round(s.beta * 100)}%.
          R² {s.r_squared.toFixed(2)} = 수익의 {Math.round(s.r_squared * 100)}% 만
          시장으로 설명, 나머지 {Math.round((1 - s.r_squared) * 100)}% 가 종목 선택 알파.
        </p>
      </section>

      {/* Projector */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">N년 후 시뮬레이션</h2>
        <StrategyProjector />
      </section>

      {/* Methodology */}
      <section className="space-y-2 text-sm">
        <h2 className="text-lg font-semibold tracking-tight">방법론</h2>
        <ul className="space-y-1.5 text-muted-foreground list-disc pl-5">
          <li>
            <strong>Universe</strong>: KOSPI+KOSDAQ 1820 ticker 전체 (4M+ fires,
            271K entry candidates 17년).
          </li>
          <li>
            <strong>신호</strong>: 책 정신 top-5 entries — volume_case_3,
            pattern_forking, volume_case_7, action_strong_buy, pattern_ma240_breakout.
          </li>
          <li>
            <strong>Hold</strong>: 24주 (6 개월). 책 정신 추세는 길게.
          </li>
          <li>
            <strong>포지션</strong>: 최대 50 종목 동시 보유. 강도 desc 우선.
            (universe scale 에서 slot 회전 필요)
          </li>
          <li>
            <strong>Stop-loss</strong>: 없음 (universe 검증 시 SL=10/5% 적용은
            return 감소). 신호별 부분 적용은 별도 분석 중.
          </li>
          <li>
            <strong>비용</strong>: 매수 0.015% + 매도 0.18% (브로커 + 거래세).
            슬리피지 0%. 양도세 5억 미만 무시.
          </li>
        </ul>
        <p className="text-xs text-muted-foreground mt-3 leading-relaxed">
          ⚠️ <strong>이전 (2026-05-23) 100-ticker random sample (+6380%) 은
          sample bias 로 over-fit</strong> 이었음을 full universe 검증으로 확인
          (2026-05-24). 위 숫자가 honest production result. KOSPI BH (CAGR 11.5%)
          대비 outperformance 는 +1.91%p/year — 책 전략의 진가는 절대 return
          보다 Sharpe (0.62) + Sortino (0.81) + 낮은 DD (47.6%) 등 risk-adjusted
          profile. 4 random seeds × walk-forward 3 folds 모두 sample-period
          dependent (+50%~+9000% 범위).
        </p>
      </section>
    </div>
  );
}

function Card({
  label, value, accent, negative,
}: {
  label: string;
  value: string;
  accent?: boolean;
  negative?: boolean;
}) {
  const tone = accent
    ? "text-emerald-600 dark:text-emerald-400"
    : negative
    ? "text-rose-600 dark:text-rose-400"
    : "text-foreground";
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 font-semibold text-lg ${tone} tabular-nums`}>
        {value}
      </div>
    </div>
  );
}
