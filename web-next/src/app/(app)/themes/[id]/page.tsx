/**
 * Theme detail — list of constituent tickers with each ticker's latest
 * scan signal (if any) for quick scanning.
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { notFound } from "next/navigation";
import { ActionBadge } from "@/components/action-badge";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";

interface PageProps {
  params: Promise<{ id: string }>;
}

const ACTION_BY_SIGNAL: Record<string, "STRONG_BUY" | "BUY" | "SELL" | "SELL_OR_SHORT" | "AVOID"> = {
  action_strong_buy: "STRONG_BUY",
  action_buy: "BUY",
  action_sell: "SELL",
  action_sell_short: "SELL_OR_SHORT",
  action_avoid: "AVOID",
};

async function fetchTheme(themeId: number) {
  const sb = getServerClient();
  const [{ data: theme }, { data: members }, { data: daily }] = await Promise.all([
    sb.from("themes").select("theme_id, name, members").eq("theme_id", themeId).maybeSingle(),
    sb.from("theme_members")
      .select("ticker, tickers:ticker(name, market, sector)")
      .eq("theme_id", themeId),
    sb.from("theme_daily")
      .select("day, change_pct_1d, change_pct_1m, leading_name, lagging_name")
      .eq("theme_id", themeId)
      .order("day", { ascending: false })
      .limit(1)
      .maybeSingle(),
  ]);
  if (!theme) return null;

  const memberTickers = (members ?? []).map((m) => m.ticker as string);
  const signalsByTicker: Record<string, { type: string; strength: number; reason: string }> = {};
  if (memberTickers.length > 0) {
    const { data: signals } = await sb
      .from("scan_results")
      .select("ticker, signal_type, strength, reason")
      .in("ticker", memberTickers)
      .like("signal_type", "action_%")
      .eq("is_active", true);
    for (const s of signals ?? []) {
      const prev = signalsByTicker[s.ticker];
      const cur = {
        type: String(s.signal_type),
        strength: Number(s.strength),
        reason: String(s.reason ?? ""),
      };
      if (!prev || cur.strength > prev.strength) signalsByTicker[s.ticker] = cur;
    }
  }

  return {
    theme,
    daily,
    members: (members ?? []).map((m) => {
      const t = (m as { tickers?: { name?: string; market?: string; sector?: string } }).tickers;
      return {
        ticker: m.ticker as string,
        name: t?.name ?? null,
        market: t?.market ?? null,
        sector: t?.sector ?? null,
        signal: signalsByTicker[m.ticker as string] ?? null,
      };
    }),
  };
}

export default async function ThemeDetailPage({ params }: PageProps) {
  const { id } = await params;
  const themeId = Number(id);
  if (!Number.isInteger(themeId)) notFound();

  const result = await fetchTheme(themeId);
  if (!result) notFound();
  const { theme, daily, members } = result;

  // Sort: BUY signals first, then by ticker
  const sorted = [...members].sort((a, b) => {
    const aBuy = a.signal?.type?.startsWith("action_strong_buy") ? 2
               : a.signal?.type?.startsWith("action_buy") ? 1 : 0;
    const bBuy = b.signal?.type?.startsWith("action_strong_buy") ? 2
               : b.signal?.type?.startsWith("action_buy") ? 1 : 0;
    if (aBuy !== bBuy) return bBuy - aBuy;
    return a.ticker.localeCompare(b.ticker);
  });

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/themes"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        테마 목록
      </Link>

      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{theme.name}</h1>
        <p className="text-sm text-muted-foreground">
          {members.length} 종목 ·{" "}
          {daily?.change_pct_1d != null
            ? <span className={Number(daily.change_pct_1d) >= 0 ? "text-rose-500" : "text-blue-500"}>
                1D {Number(daily.change_pct_1d) >= 0 ? "+" : ""}{Number(daily.change_pct_1d).toFixed(2)}%
              </span>
            : null}
          {daily?.change_pct_1m != null && (
            <>
              {" · "}
              <span className="text-muted-foreground">
                1M {Number(daily.change_pct_1m) >= 0 ? "+" : ""}{Number(daily.change_pct_1m).toFixed(2)}%
              </span>
            </>
          )}
        </p>
      </header>

      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr className="text-left">
              <th className="px-3 py-2 font-medium text-muted-foreground">티커</th>
              <th className="px-3 py-2 font-medium text-muted-foreground">종목명</th>
              <th className="px-3 py-2 font-medium text-muted-foreground">시장</th>
              <th className="px-3 py-2 font-medium text-muted-foreground">섹터</th>
              <th className="px-3 py-2 font-medium text-muted-foreground">신호</th>
              <th className="px-3 py-2 font-medium text-muted-foreground text-right">강도</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((m) => {
              const action = m.signal ? ACTION_BY_SIGNAL[m.signal.type] : null;
              return (
                <tr key={m.ticker} className="border-t border-border hover:bg-muted/30 transition-colors">
                  <td className="px-3 py-2 font-mono">
                    <Link href={`/stocks/${encodeURIComponent(m.ticker)}`} className="hover:underline">
                      {m.ticker}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{m.name ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{m.market ?? "—"}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-[180px]">
                    {m.sector ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    {action ? <ActionBadge action={action} size="sm" /> : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {m.signal?.strength?.toFixed(2) ?? "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {sorted.length === 0 && (
          <div className="py-12 text-center text-muted-foreground text-sm">
            테마 멤버 데이터가 없습니다. 매주 금요일 자동 갱신.
          </div>
        )}
      </div>
    </div>
  );
}
