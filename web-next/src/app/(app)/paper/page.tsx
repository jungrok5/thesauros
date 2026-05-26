/**
 * /paper — 모의 투자 (forward-test) 페이지.
 *
 * Broker-standard view (2026-05-27 reform): each row = one POSITION
 * (ticker × open-era). Expand a row to see its fill log (매수 / 추매
 * / 분할 매도 / 청산).
 *
 * Stats panel:
 *   · Position-level header (진행 중 N · 투자액 · 현재 평가 · 수익률)
 *   · Fill-level closed stats (sell fills): 승률 / 평균 / payoff /
 *     평균 보유 / best / worst
 *   · /backtest 비교 패널 (default collapsed)
 */
import Link from "next/link";
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { ensureUserId } from "@/lib/supabase";
import {
  fetchAllPositions, computeStats, BACKTEST_REFERENCE,
  type PaperPositionLive,
} from "@/lib/paper-trades";
import { PaperCloseButton } from "@/components/paper-close-button";

export const dynamic = "force-dynamic";

export default async function PaperPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");
  const userId = await ensureUserId(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );

  const positions = await fetchAllPositions(userId);
  const stats = computeStats(positions);
  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status !== "open");

  return (
    <div className="space-y-6 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          📒 모의 투자 (Forward Test)
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          실제 매수 아닌 시뮬레이션. 종목 상세에서{" "}
          <span className="font-mono">📒 모의 투자</span> 클릭해서 추가합니다.
          같은 종목 매수는 같은 position 에 추매 fill 로 누적 — broker 표준 패턴.
          행 클릭하면 fill 내역 (매수 / 추매 / 분할 매도) 펼침.
        </p>
      </header>

      <section className="rounded-xl border-2 border-foreground/20 bg-muted/30 p-4 space-y-3">
        <h2 className="text-base font-semibold">📊 종합</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="진행 중" value={`${stats.open_positions} 종목`} />
          <Stat label="투자액"
            value={`${(stats.total_invested_open_krw / 10_000).toLocaleString(undefined, { maximumFractionDigits: 0 })}만원`} />
          <Stat label="현재 평가"
            value={`${(stats.total_current_value_krw / 10_000).toLocaleString(undefined, { maximumFractionDigits: 0 })}만원`}
            tone={stats.total_unrealized_pnl_krw >= 0 ? "up" : "down"} />
          <Stat
            label="총 수익률 (실현+미실현)"
            value={`${stats.total_pnl_pct >= 0 ? "+" : ""}${stats.total_pnl_pct.toFixed(2)}%`}
            tone={stats.total_pnl_pct >= 0 ? "up" : "down"}
          />
        </div>
        {stats.closed_fills > 0 && (
          <div className="space-y-2 pt-2 border-t border-border/50">
            <div className="flex flex-wrap gap-3 text-xs">
              <span className="text-muted-foreground">청산 매도 fill {stats.closed_fills}건</span>
              {stats.win_rate != null && (
                <span>승률 <strong>{Math.round(stats.win_rate * 100)}%</strong></span>
              )}
              {stats.avg_pnl_pct != null && (
                <span>평균 <strong>{stats.avg_pnl_pct >= 0 ? "+" : ""}{stats.avg_pnl_pct.toFixed(1)}%/fill</strong></span>
              )}
              {stats.payoff != null && (
                <span>payoff <strong>{stats.payoff.toFixed(2)}</strong></span>
              )}
              {stats.avg_hold_days != null && (
                <span>평균 보유 <strong>{stats.avg_hold_days}일</strong></span>
              )}
              {stats.best_pct != null && (
                <span>최고 <strong className="text-emerald-600 dark:text-emerald-400">
                  +{stats.best_pct.toFixed(1)}%</strong></span>
              )}
              {stats.worst_pct != null && (
                <span>최저 <strong className="text-rose-600 dark:text-rose-400">
                  {stats.worst_pct.toFixed(1)}%</strong></span>
              )}
            </div>
            <BacktestComparison stats={stats} />
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">진행 중</h2>
        {open.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
            아직 모의 투자 종목이 없습니다. <Link href="/screener"
              className="text-foreground hover:underline">스크리너</Link>{" "}
            에서 종목 발견 → 📒 모의 투자 클릭.
          </div>
        ) : (
          <PositionList rows={open} closable />
        )}
      </section>

      {closed.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold tracking-tight">청산 완료</h2>
          <PositionList rows={closed} closable={false} />
        </section>
      )}
    </div>
  );
}


function BacktestComparison({ stats }: {
  stats: ReturnType<typeof computeStats>;
}) {
  const yours = [
    { label: "승률", user: stats.win_rate != null ? `${Math.round(stats.win_rate * 100)}%` : "—",
      ref: `${Math.round(BACKTEST_REFERENCE.win_rate * 100)}%` },
    { label: "평균 수익률 / fill",
      user: stats.avg_pnl_pct != null
        ? `${stats.avg_pnl_pct >= 0 ? "+" : ""}${stats.avg_pnl_pct.toFixed(2)}%`
        : "—",
      ref: `+${BACKTEST_REFERENCE.avg_pnl_pct.toFixed(2)}%` },
    { label: "winner 평균",
      user: stats.avg_win_pct != null
        ? `+${stats.avg_win_pct.toFixed(1)}%` : "—",
      ref: `+${BACKTEST_REFERENCE.avg_win_pct.toFixed(1)}%` },
    { label: "loser 평균",
      user: stats.avg_loss_pct != null
        ? `${stats.avg_loss_pct.toFixed(1)}%` : "—",
      ref: `${BACKTEST_REFERENCE.avg_loss_pct.toFixed(1)}%` },
    { label: "payoff",
      user: stats.payoff != null ? stats.payoff.toFixed(2) : "—",
      ref: BACKTEST_REFERENCE.payoff.toFixed(2) },
  ];
  return (
    <details className="rounded-md border border-border bg-background/50 px-3 py-2 text-[11px] leading-relaxed">
      <summary className="cursor-pointer font-medium text-muted-foreground hover:text-foreground select-none">
        📊 내 forward-test vs 17년 backtest 비교
      </summary>
      <div className="mt-3 space-y-2">
        <div className="grid grid-cols-3 gap-2 text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border/50 pb-1">
          <div>지표</div>
          <div className="text-right">내 forward-test</div>
          <div className="text-right">17년 backtest</div>
        </div>
        {yours.map((r) => (
          <div key={r.label} className="grid grid-cols-3 gap-2 font-mono">
            <div className="text-muted-foreground font-sans">{r.label}</div>
            <div className="text-right">{r.user}</div>
            <div className="text-right text-muted-foreground">{r.ref}</div>
          </div>
        ))}
        <p className="text-[10px] text-muted-foreground pt-2 border-t border-border/50 leading-relaxed">
          ⚠️ 표본 크기 차이 — backtest = 271K trades × 17년, 내 forward-test =
          {" "}{stats.closed_fills}건. 적은 표본이라 변동성 큼. 책 정신: 분산 + 시간이 시스템 가치를 만든다.
        </p>
      </div>
    </details>
  );
}


function Stat({ label, value, tone }: {
  label: string; value: string; tone?: "up" | "down";
}) {
  const cls = tone === "up"
    ? "text-emerald-600 dark:text-emerald-400"
    : tone === "down"
      ? "text-rose-600 dark:text-rose-400"
      : "text-foreground";
  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${cls}`}>
        {value}
      </div>
    </div>
  );
}


function PositionList({ rows, closable }: {
  rows: PaperPositionLive[]; closable: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-card divide-y divide-border">
      {rows.map((p) => (
        <PositionRow key={p.id} p={p} closable={closable} />
      ))}
    </div>
  );
}


function PositionRow({ p, closable }: {
  p: PaperPositionLive; closable: boolean;
}) {
  const buyCount = p.fills.filter((f) => f.side === "buy").length;
  const sellCount = p.fills.filter((f) => f.side === "sell").length;
  return (
    <details className="group">
      <summary className="grid grid-cols-12 gap-2 items-center px-3 py-2.5 text-xs cursor-pointer hover:bg-muted/40 select-none">
        <div className="col-span-3">
          <Link href={`/stocks/${encodeURIComponent(p.ticker)}?from=paper`}
            onClick={(e) => e.stopPropagation()}
            className="block hover:underline">
            <div className="font-mono text-[11px]">{p.ticker}</div>
            <div className="text-[10px] text-muted-foreground mt-0.5">
              {(p.total_invested_krw / 10_000).toLocaleString(undefined, { maximumFractionDigits: 0 })}만원 · 매수 {buyCount}건
              {sellCount > 0 && ` · 매도 ${sellCount}건`}
            </div>
          </Link>
        </div>
        <div className="col-span-2 text-right font-mono">
          평단 {p.avg_cost != null ? fmt(p.avg_cost) : "—"}
        </div>
        <div className="col-span-2 text-right font-mono">
          현재 {p.current_price != null ? fmt(p.current_price) : "—"}
        </div>
        <div className={`col-span-2 text-right font-mono ${
          p.total_return_pct > 0 ? "text-emerald-600 dark:text-emerald-400"
          : p.total_return_pct < 0 ? "text-rose-600 dark:text-rose-400" : ""
        }`}>
          {p.total_return_pct > 0 ? "+" : ""}{p.total_return_pct.toFixed(1)}%
        </div>
        <div className="col-span-2 text-left">
          {p.status === "open" && p.stop_hit && (
            <span className="text-xs rounded px-1.5 py-0.5 bg-rose-500/15 text-rose-700 dark:text-rose-300">
              ⚠ 손절 도달
            </span>
          )}
          {p.status === "open" && p.target_hit && (
            <span className="text-xs rounded px-1.5 py-0.5 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
              🎯 목표 도달
            </span>
          )}
          {p.status === "open" && !p.stop_hit && !p.target_hit && (
            <span className="text-xs text-muted-foreground">진행 중</span>
          )}
          {p.status === "closed" && (
            <span className="text-xs text-muted-foreground">청산 완료</span>
          )}
        </div>
        <div className="col-span-1 text-right">
          {closable && p.shares_open > 0 &&
            <PaperCloseButton id={p.id} ticker={p.ticker} />}
        </div>
      </summary>
      {/* Fill detail */}
      <div className="px-3 py-2 bg-muted/10 border-t border-border text-[11px]">
        <div className="font-medium mb-1.5 text-muted-foreground">
          📜 Fill 내역 ({p.fills.length}건)
        </div>
        {p.fills.length === 0 ? (
          <div className="text-muted-foreground">no fills</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-muted-foreground border-b border-border/40">
                <th className="text-left py-1">날짜</th>
                <th className="text-left py-1">side</th>
                <th className="text-right py-1">가격</th>
                <th className="text-right py-1">주수</th>
                <th className="text-right py-1">금액</th>
                <th className="text-right py-1">P&L</th>
                <th className="text-left py-1 pl-3">사유</th>
              </tr>
            </thead>
            <tbody>
              {p.fills.map((f) => (
                <tr key={f.id} className="border-b border-border/30 last:border-b-0">
                  <td className="py-1">{f.fill_date}</td>
                  <td className={f.side === "buy"
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-rose-600 dark:text-rose-400"}>
                    {f.side === "buy" ? "매수" : "매도"}
                  </td>
                  <td className="text-right font-mono">{fmt(f.fill_price)}</td>
                  <td className="text-right font-mono">{f.shares.toFixed(2)}</td>
                  <td className="text-right font-mono">
                    {(f.amount_krw / 10_000).toLocaleString(undefined, { maximumFractionDigits: 0 })}만
                  </td>
                  <td className={`text-right font-mono ${
                    f.pnl_pct == null ? "" :
                    f.pnl_pct > 0 ? "text-emerald-600 dark:text-emerald-400"
                    : f.pnl_pct < 0 ? "text-rose-600 dark:text-rose-400" : ""
                  }`}>
                    {f.pnl_pct != null
                      ? `${f.pnl_pct > 0 ? "+" : ""}${f.pnl_pct.toFixed(1)}%` : "—"}
                  </td>
                  <td className="pl-3 text-muted-foreground">{f.reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </details>
  );
}


function fmt(n: number): string {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}
