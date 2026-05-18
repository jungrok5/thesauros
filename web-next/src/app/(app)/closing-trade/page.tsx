/**
 * 종가매매 모드 (구 "와병투자") —
 *  매일 16시 책 신호 자동 갱신. 보유 종목 10MA 신호등 + 매매 일지.
 *  책 가르침: "매매는 안 할수록 좋다 — 주봉 매매 금요일 15시, 월봉 매매 매월 말일 15시"
 */
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import Link from "next/link";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { TradeLogForm } from "@/components/trade-log-form";
import { MarketHoursNotice } from "@/components/market-hours-notice";

export const dynamic = "force-dynamic";

/* Next closing-time helpers */

// KRX regular session closes at 15:30 KST. The book's decision points
// are "오후 3시" (close-time), so we anchor weekly/monthly checkpoints
// at 15:30 — same as the actual market close.
function nextWeeklyClose(now: Date): Date {
  const d = new Date(now);
  const day = d.getDay(); // 0=Sun ... 6=Sat
  const daysUntilFri = (5 - day + 7) % 7;
  d.setDate(d.getDate() + daysUntilFri);
  d.setHours(15, 30, 0, 0);
  if (daysUntilFri === 0 && (now.getHours() > 15 || (now.getHours() === 15 && now.getMinutes() >= 30))) {
    d.setDate(d.getDate() + 7);
  }
  return d;
}

function nextMonthlyClose(now: Date): Date {
  const d = new Date(now.getFullYear(), now.getMonth() + 1, 0, 15, 30, 0);
  if (d.getTime() < now.getTime()) {
    return new Date(now.getFullYear(), now.getMonth() + 2, 0, 15, 30, 0);
  }
  return d;
}

function daysBetween(a: Date, b: Date): number {
  return Math.ceil((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24));
}

async function fetchHoldingsWithSignals(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();
  const { data: watch } = await sb
    .from("watchlist")
    .select("ticker, category, entry_price, entry_date, note, tickers:ticker(name, market)")
    .eq("user_id", userId)
    .order("created_at", { ascending: false });

  const watchList = watch ?? [];
  const tickers = watchList.map((w) => w.ticker);

  const signalsByTicker: Record<string, { type: string; strength: number; reason: string }[]> = {};
  if (tickers.length > 0) {
    const { data: signals } = await sb
      .from("scan_results")
      .select("ticker, signal_type, strength, reason, timeframe")
      .in("ticker", tickers)
      .eq("is_active", true);
    for (const s of signals ?? []) {
      signalsByTicker[s.ticker] = signalsByTicker[s.ticker] ?? [];
      signalsByTicker[s.ticker].push({
        type: String(s.signal_type),
        strength: Number(s.strength),
        reason: String(s.reason ?? ""),
      });
    }
  }

  return watchList.map((w) => {
    const t = (w as { tickers?: { name?: string; market?: string } }).tickers;
    const sigs = signalsByTicker[w.ticker] ?? [];
    const exit = sigs.find((s) =>
      s.type.startsWith("action_sell")
      || s.type.startsWith("pattern_double_top")
      || s.type.startsWith("pattern_head_and_shoulders")
      || s.type.startsWith("pattern_triple_top")
      || s.type.startsWith("pattern_death_messenger")
    );
    const buy = sigs.find((s) =>
      s.type === "action_strong_buy" || s.type === "action_buy"
    );
    let status: "green" | "yellow" | "red" | "gray";
    let statusLabel: string;
    if (exit) { status = "red"; statusLabel = "🔴 청산 검토"; }
    else if (buy) { status = "green"; statusLabel = "🟢 매수 신호"; }
    else if (sigs.length > 0) { status = "yellow"; statusLabel = "🟡 신호 있음"; }
    else { status = "gray"; statusLabel = "⚪ 신호 없음"; }
    return {
      ...w,
      ticker_name: t?.name ?? null,
      ticker_market: t?.market ?? null,
      signals: sigs,
      status,
      statusLabel,
      exit,
      buy,
    };
  });
}

async function fetchTradeLog(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();
  const { data } = await sb
    .from("trade_log")
    .select("*, tickers:ticker(name)")
    .eq("user_id", userId)
    .order("trade_date", { ascending: false })
    .limit(30);
  return (data ?? []).map((r) => {
    const t = (r as { tickers?: { name?: string } }).tickers;
    return { ...r, ticker_name: t?.name ?? null };
  });
}

export default async function ClosingTradePage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");

  const email = session.user.email.toLowerCase();
  const name = session.user.name ?? null;
  const [holdings, log] = await Promise.all([
    fetchHoldingsWithSignals(email, name),
    fetchTradeLog(email, name),
  ]);

  const holdingsOnly = holdings.filter((h) => h.category === "holding");
  const observing = holdings.filter((h) => h.category === "observing");

  const now = new Date();
  const wk = nextWeeklyClose(now);
  const mo = nextMonthlyClose(now);

  return (
    <div className="space-y-8 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">종가매매 모드</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          책 가르침: 매매는 안 할수록 좋습니다. 주봉 매매는 금요일 15시,
          월봉 매매는 매월 말일 15시에만 확인하세요.
        </p>
      </header>

      <MarketHoursNotice />

      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wide">다음 주봉 마감</div>
          <div className="mt-1 text-xl font-mono">
            {wk.toLocaleDateString("ko-KR")} (금) 15:30
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            D-{Math.max(0, daysBetween(now, wk))} · 책: 금요일 15시 1회 확인
          </div>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs text-muted-foreground uppercase tracking-wide">다음 월봉 마감</div>
          <div className="mt-1 text-xl font-mono">
            {mo.toLocaleDateString("ko-KR")} 15:30
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            D-{Math.max(0, daysBetween(now, mo))} · 책: 매월 말일 15시 1회
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          보유 종목 ({holdingsOnly.length})
        </h2>
        {holdingsOnly.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
            보유 종목이 없습니다.{" "}
            <Link href="/recommendations" className="underline">추천 종목</Link>에서 등록하세요.
          </div>
        ) : (
          <ul className="space-y-2">
            {holdingsOnly.map((h) => (
              <li
                key={h.ticker}
                className={`rounded-lg border p-3 ${
                  h.status === "red" ? "border-rose-500/40 bg-rose-500/5"
                    : h.status === "green" ? "border-emerald-500/40 bg-emerald-500/5"
                      : h.status === "yellow" ? "border-amber-500/40 bg-amber-500/5"
                        : "border-border bg-card"
                }`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div className="flex items-baseline gap-2">
                    <Link
                      href={`/stocks/${encodeURIComponent(h.ticker)}`}
                      className="font-mono text-sm font-semibold hover:underline"
                    >
                      {h.ticker}
                    </Link>
                    <span className="text-sm">{h.ticker_name ?? "—"}</span>
                  </div>
                  <span className="text-sm">{h.statusLabel}</span>
                </div>
                {h.entry_price != null && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    진입가 {h.entry_price.toLocaleString("ko-KR")}원
                    {h.entry_date && ` · ${h.entry_date}`}
                  </div>
                )}
                {h.exit && (
                  <div className="mt-1 text-xs text-rose-700 dark:text-rose-300">
                    ⚠️ {h.exit.reason}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {observing.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            관찰 중 ({observing.length})
          </h2>
          <ul className="space-y-2">
            {observing.map((h) => (
              <li
                key={h.ticker}
                className="rounded-lg border border-border bg-card p-3"
              >
                <div className="flex items-baseline justify-between gap-2 flex-wrap">
                  <div className="flex items-baseline gap-2">
                    <Link
                      href={`/stocks/${encodeURIComponent(h.ticker)}`}
                      className="font-mono text-sm font-semibold hover:underline"
                    >
                      {h.ticker}
                    </Link>
                    <span className="text-sm">{h.ticker_name ?? "—"}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">{h.statusLabel}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          매매 일지 ({log.length})
        </h2>
        <TradeLogForm />
        {log.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
            아직 기록된 매매가 없습니다.
          </div>
        ) : (
          <ul className="divide-y divide-border rounded-lg border border-border">
            {log.map((t) => (
              <li key={t.id} className="px-3 py-2 text-sm flex flex-wrap items-baseline gap-3">
                <span className="text-xs text-muted-foreground">{t.trade_date}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded ${
                  t.action === "buy"
                    ? "bg-emerald-500/15 text-emerald-700"
                    : "bg-rose-500/15 text-rose-700"
                }`}>
                  {t.action === "buy" ? "매수" : "매도"}
                </span>
                <span className="font-mono">{t.ticker}</span>
                <span>{t.ticker_name ?? ""}</span>
                <span className="font-mono">{Number(t.price).toLocaleString("ko-KR")}원</span>
                {t.quantity && <span className="text-muted-foreground">× {t.quantity}</span>}
                {t.reason && <span className="text-xs text-muted-foreground italic">{t.reason}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
