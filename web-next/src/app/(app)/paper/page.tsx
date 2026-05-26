/**
 * /paper — 가짜 매수 (forward-test) 페이지.
 *
 * Server component. Fetches the user's paper trades, decorates with
 * live prices, computes aggregate stats, and renders the list.
 * Closing a trade goes through PaperCloseButton (client component).
 *
 * Mirrors the book's framework:
 *   · Each row shows entry / stop / target — the same numbers the
 *     BookVerdict surfaced when "매수" was clicked.
 *   · current price + P&L update on every page load (server-rendered
 *     with force-dynamic so 새로고침 = 최신).
 *   · stop_hit / target_hit chips light up so the user can decide.
 */
import Link from "next/link";
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { ensureUserId } from "@/lib/supabase";
import {
  fetchAllTradesForUser, computeStats, type PaperTradeLive,
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

  const rows = await fetchAllTradesForUser(userId);
  const stats = computeStats(rows);
  const open = rows.filter((r) => r.status === "open");
  const closed = rows.filter((r) => r.status !== "open");

  return (
    <div className="space-y-6 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          📒 가짜 매수 (Forward Test)
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          실제 매수 아닌 시뮬레이션. 종목 상세 또는 스크리너에서{" "}
          <span className="font-mono">📒 가짜 매수</span> 클릭해서 추가합니다.
          진입가 / 손절 / 목표는 매수 시점 BookVerdict 의 값을 그대로
          snapshot — 같은 의사결정 프레임 그대로 추적.
        </p>
      </header>

      <section className="rounded-xl border-2 border-foreground/20 bg-muted/30 p-4 space-y-3">
        <h2 className="text-base font-semibold">📊 종합</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="진행 중" value={`${stats.open_n} 종목`} />
          <Stat label="투자액"
            value={`${(stats.total_invested_krw / 10_000).toLocaleString()}만원`} />
          <Stat label="현재 평가"
            value={`${(stats.total_current_value_krw / 10_000).toLocaleString()}만원`}
            tone={stats.total_pnl_krw >= 0 ? "up" : "down"} />
          <Stat
            label="수익률"
            value={`${stats.total_pnl_pct >= 0 ? "+" : ""}${stats.total_pnl_pct.toFixed(2)}%`}
            tone={stats.total_pnl_krw >= 0 ? "up" : "down"}
          />
        </div>
        {stats.closed_n > 0 && (
          <div className="flex flex-wrap gap-3 text-xs pt-2 border-t border-border/50">
            <span className="text-muted-foreground">청산 완료 {stats.closed_n}건</span>
            {stats.win_rate != null && (
              <span>승률 <strong>{Math.round(stats.win_rate * 100)}%</strong></span>
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
        )}
      </section>

      {/* Open trades */}
      <section className="space-y-2">
        <h2 className="text-lg font-semibold tracking-tight">진행 중</h2>
        {open.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
            아직 가짜 매수 종목이 없습니다. <Link href="/screener"
              className="text-foreground hover:underline">스크리너</Link>{" "}
            에서 종목 발견 → 📒 가짜 매수 클릭.
          </div>
        ) : (
          <TradesTable rows={open} closable />
        )}
      </section>

      {/* Closed trades */}
      {closed.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold tracking-tight">청산 완료</h2>
          <TradesTable rows={closed} closable={false} />
        </section>
      )}
    </div>
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


function TradesTable({ rows, closable }: {
  rows: PaperTradeLive[]; closable: boolean;
}) {
  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">종목</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">진입</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">현재</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">손익</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">손절 / 목표</th>
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">상태</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}
                className="border-b border-border last:border-b-0">
                <td className="px-3 py-2">
                  <Link href={`/stocks/${encodeURIComponent(r.ticker)}?from=paper`}
                    className="hover:underline">
                    <div className="font-mono text-[11px]">{r.ticker}</div>
                  </Link>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    {r.entry_date} · {(r.amount_krw / 10_000).toLocaleString()}만원
                  </div>
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {fmt(r.entry_price)}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {r.current_price != null ? fmt(r.current_price) : "—"}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${
                  r.pnl_pct == null ? "" :
                  r.pnl_pct > 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : r.pnl_pct < 0
                      ? "text-rose-600 dark:text-rose-400"
                      : ""
                }`}>
                  {r.pnl_pct != null
                    ? `${r.pnl_pct > 0 ? "+" : ""}${r.pnl_pct.toFixed(1)}%`
                    : "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {r.stop_loss != null
                    ? <span className="text-rose-600/80 dark:text-rose-400/80">
                        {fmt(r.stop_loss)}
                      </span>
                    : "—"}
                  {" / "}
                  {r.target != null
                    ? <span className="text-emerald-600/80 dark:text-emerald-400/80">
                        {fmt(r.target)}
                      </span>
                    : "—"}
                </td>
                <td className="px-3 py-2 text-left">
                  {r.status === "open" && r.stop_hit && (
                    <span className="text-xs rounded px-1.5 py-0.5
                                     bg-rose-500/15 text-rose-700 dark:text-rose-300">
                      ⚠ 손절선 hit
                    </span>
                  )}
                  {r.status === "open" && r.target_hit && (
                    <span className="text-xs rounded px-1.5 py-0.5
                                     bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                      🎯 목표 도달
                    </span>
                  )}
                  {r.status === "open" && !r.stop_hit && !r.target_hit && (
                    <span className="text-xs text-muted-foreground">진행 중</span>
                  )}
                  {r.status === "closed_stop" && (
                    <span className="text-xs rounded px-1.5 py-0.5
                                     bg-rose-500/15 text-rose-700 dark:text-rose-300">
                      손절 청산
                    </span>
                  )}
                  {r.status === "closed_target" && (
                    <span className="text-xs rounded px-1.5 py-0.5
                                     bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                      목표 달성
                    </span>
                  )}
                  {r.status === "closed_manual" && (
                    <span className="text-xs rounded px-1.5 py-0.5
                                     bg-zinc-500/15 text-zinc-700 dark:text-zinc-300">
                      수동 청산
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {closable && <PaperCloseButton id={r.id} ticker={r.ticker} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function fmt(n: number): string {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}
