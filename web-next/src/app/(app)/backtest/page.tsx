import {
  api,
  type BacktestReport,
  type BookCasesResponse,
} from "@/lib/api";
import { formatNumber, formatPct, cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

interface SearchParams {
  ticker?: string;
  strategy?: "monthly_10ma" | "weekly_10ma";
}

function StatTile({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground mb-1">{label}</div>
      <div className={cn("text-2xl font-mono font-medium", className)}>
        {value}
      </div>
    </div>
  );
}

function ReportView({ r }: { r: BacktestReport }) {
  const outperforms = r.total_return_pct > r.buy_and_hold_return_pct;
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold font-mono">{r.ticker}</h2>
        <p className="text-sm text-muted-foreground mt-1">
          전략: <span className="font-medium">{r.strategy}</span> · {r.period}
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label="거래 횟수"
          value={String(r.n_trades)}
        />
        <StatTile
          label="승률"
          value={`${r.win_rate.toFixed(1)}%`}
          className={
            r.win_rate >= 50
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-rose-600 dark:text-rose-400"
          }
        />
        <StatTile
          label="평균 거래 수익률"
          value={formatPct(r.avg_return_pct)}
        />
        <StatTile
          label="최악 단일 거래"
          value={formatPct(r.max_drawdown_trade)}
          className="text-rose-600 dark:text-rose-400"
        />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatTile
          label="총 누적 수익률"
          value={formatPct(r.total_return_pct)}
          className={
            outperforms
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-foreground"
          }
        />
        <StatTile
          label="Buy & Hold 비교"
          value={formatPct(r.buy_and_hold_return_pct)}
        />
        <StatTile
          label="평균 승리"
          value={formatPct(r.avg_gain_winners)}
          className="text-emerald-600 dark:text-emerald-400"
        />
        <StatTile
          label="평균 패배"
          value={formatPct(r.avg_loss_losers)}
          className="text-rose-600 dark:text-rose-400"
        />
      </div>

      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="px-4 py-2 border-b border-border bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
          거래 내역 ({r.trades.length})
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Entry</th>
                <th className="px-3 py-2 font-medium">Exit</th>
                <th className="px-3 py-2 font-medium text-right">Entry $</th>
                <th className="px-3 py-2 font-medium text-right">Exit $</th>
                <th className="px-3 py-2 font-medium text-right">Return</th>
                <th className="px-3 py-2 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody>
              {r.trades.map((t, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="px-3 py-1.5 font-mono">{t.entry_date}</td>
                  <td className="px-3 py-1.5 font-mono">
                    {t.exit_date ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-right">
                    {formatNumber(t.entry_price)}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-right">
                    {t.exit_price !== null ? formatNumber(t.exit_price) : "—"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 font-mono text-right",
                      (t.return_pct ?? 0) >= 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-rose-600 dark:text-rose-400",
                    )}
                  >
                    {t.return_pct !== null ? formatPct(t.return_pct) : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {t.exit_reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default async function BacktestPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const sp = await searchParams;
  const ticker = sp.ticker?.trim().toUpperCase() ?? "";
  const strategy = (sp.strategy ?? "monthly_10ma") as
    | "monthly_10ma"
    | "weekly_10ma";

  let report: BacktestReport | null = null;
  let cases: BookCasesResponse | null = null;
  let error: string | null = null;

  // Always load book cases
  try {
    cases = await api.bookCases();
  } catch (e) {
    error = String(e);
  }

  if (ticker) {
    try {
      report = await api.backtest(ticker, strategy);
    } catch (e) {
      error = String(e);
    }
  }

  return (
    <div className="space-y-8 max-w-7xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Backtest</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          책 룰(월봉 / 주봉 10MA 추세 추종)을 과거 데이터에 적용한 결과.
          승률·평균 수익·B&amp;H 비교·MDD 한눈에.
        </p>
      </header>

      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
          단일 종목 백테스트
        </h2>
        <form method="GET" className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              Ticker
            </label>
            <input
              name="ticker"
              defaultValue={ticker}
              placeholder="AAPL, 005930.KS …"
              className="px-3 py-2 rounded-md border border-input bg-background text-sm w-48 font-mono"
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              전략
            </label>
            <select
              name="strategy"
              defaultValue={strategy}
              className="px-3 py-2 rounded-md border border-input bg-background text-sm"
            >
              <option value="monthly_10ma">월봉 10MA (책 권장)</option>
              <option value="weekly_10ma">주봉 10MA</option>
            </select>
          </div>
          <button
            type="submit"
            className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90"
          >
            백테스트
          </button>
        </form>

        {ticker && error && (
          <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-3 text-sm">
            <div className="font-medium text-rose-700 dark:text-rose-300">
              백테스트 실패
            </div>
            <div className="mt-1 font-mono text-xs">{error}</div>
          </div>
        )}

        {report && <ReportView r={report} />}
      </section>

      <section className="rounded-xl border border-border bg-card p-5 space-y-3">
        <div>
          <h2 className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
            책 사례 검증
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            책에 인용된 사례 종목들을 책의 룰로 자동 백테스트한 결과.
          </p>
        </div>

        {!cases ? (
          <div className="text-sm text-muted-foreground">로딩 중...</div>
        ) : (
          <div className="overflow-x-auto -mx-5">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr className="text-left">
                  <th className="px-5 py-2 font-medium text-muted-foreground">
                    Ticker
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground">
                    책 사례 / 기간
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    책 주장
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Trades
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Win %
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    Total
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    B&amp;H
                  </th>
                  <th className="px-3 py-2 font-medium text-muted-foreground text-right">
                    MDD/거래
                  </th>
                </tr>
              </thead>
              <tbody>
                {cases.items.map((c) => (
                  <tr
                    key={c.ticker}
                    className="border-t border-border hover:bg-muted/20"
                  >
                    <td className="px-5 py-2 font-mono">{c.ticker}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {c.claim_period}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-xs">
                      {c.book_claim_pct ? `+${c.book_claim_pct}%` : "—"}
                    </td>
                    {c.error ? (
                      <td
                        colSpan={5}
                        className="px-3 py-2 text-xs text-rose-700 dark:text-rose-400"
                      >
                        {c.error}
                      </td>
                    ) : (
                      <>
                        <td className="px-3 py-2 text-right font-mono text-xs">
                          {c.n_trades}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs">
                          {c.win_rate_pct?.toFixed(0)}%
                        </td>
                        <td
                          className={cn(
                            "px-3 py-2 text-right font-mono text-xs",
                            (c.total_return_pct ?? 0) >= 0
                              ? "text-emerald-600 dark:text-emerald-400"
                              : "text-rose-600 dark:text-rose-400",
                          )}
                        >
                          {c.total_return_pct !== undefined
                            ? formatPct(c.total_return_pct)
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs text-muted-foreground">
                          {c.buy_and_hold_return_pct !== undefined
                            ? formatPct(c.buy_and_hold_return_pct)
                            : "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-xs text-rose-600 dark:text-rose-400">
                          {c.max_drawdown_trade_pct !== undefined
                            ? formatPct(c.max_drawdown_trade_pct)
                            : "—"}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
