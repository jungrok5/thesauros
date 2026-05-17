/**
 * Watchlist — per-user list, fetched server-side by NextAuth email.
 *
 * Client-side delete via /api/watchlist (handled by `WatchlistRow`).
 */
import Link from "next/link";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { redirect } from "next/navigation";
import { WatchlistRowClient } from "./row-client";

export const dynamic = "force-dynamic";

type RawWatchlistRow = {
  id: number;
  ticker: string;
  category: "observing" | "holding";
  entry_price: number | null;
  entry_date: string | null;
  note: string | null;
  alerts_enabled: boolean;
  target_price: number | null;
  target_pct_from_entry: number | null;
  stop_price: number | null;
  stop_pct_from_entry: number | null;
  target_hit_at: string | null;
  stop_hit_at: string | null;
  created_at: string;
  tickers?: { name?: string; market?: string } | null;
};

async function fetchWatchlist(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();
  const { data, error } = await sb
    .from("watchlist")
    .select(
      "id, ticker, category, entry_price, entry_date, note, alerts_enabled, " +
        "target_price, target_pct_from_entry, stop_price, stop_pct_from_entry, " +
        "target_hit_at, stop_hit_at, created_at, tickers:ticker(name, market)",
    )
    .eq("user_id", userId)
    .order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  const rows = (data ?? []) as unknown as RawWatchlistRow[];
  return rows.map((r) => ({
    ...r,
    ticker_name: r.tickers?.name ?? null,
    ticker_market: r.tickers?.market ?? null,
  }));
}

export default async function WatchlistPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");

  const rows = await fetchWatchlist(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );

  const holding = rows.filter((r) => r.category === "holding");
  const observing = rows.filter((r) => r.category === "observing");

  return (
    <div className="space-y-8 max-w-5xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">관심 종목</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          종가매매 모드 — 매일 16시 책 신호 자동 갱신. 보유 종목에 EXIT 신호 발생 시 텔레그램 알림.
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          보유 ({holding.length})
        </h2>
        {holding.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
            보유 종목이 없습니다. 종목 상세 페이지에서 &quot;보유 추가&quot; 로 등록하세요.
          </div>
        ) : (
          <ul className="space-y-2">
            {holding.map((r) => (
              <li key={r.id}>
                <WatchlistRowClient row={r} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          관찰 ({observing.length})
        </h2>
        {observing.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
            관찰 중인 종목이 없습니다.{" "}
            <Link href="/recommendations" className="underline">추천 종목</Link> 또는{" "}
            <Link href="/stocks" className="underline">종목 검색</Link>에서 추가하세요.
          </div>
        ) : (
          <ul className="space-y-2">
            {observing.map((r) => (
              <li key={r.id}>
                <WatchlistRowClient row={r} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
