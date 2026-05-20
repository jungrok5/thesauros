import Link from "next/link";
import { TickerSearch } from "@/components/ticker-search";
import { auth } from "@/auth";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { ClearHistoryButton } from "@/components/clear-history-button";

export const dynamic = "force-dynamic";

type HistoryRow = {
  query: string;
  ticker: string | null;
  created_at: string;
};

async function fetchHistory(limit = 15): Promise<HistoryRow[]> {
  const session = await auth();
  if (!session?.user?.email) return [];
  try {
    const userId = await ensureUserId(
      session.user.email.toLowerCase(),
      session.user.name ?? null,
    );
    const sb = getServerClient();
    const { data, error } = await sb
      .from("search_history")
      .select("query, ticker, created_at")
      .eq("user_id", userId)
      .order("created_at", { ascending: false })
      .limit(limit);
    if (error) {
      console.error("search_history read:", error.message);
      return [];
    }
    return (data ?? []) as HistoryRow[];
  } catch {
    return [];
  }
}

export default async function StockSearchPage() {
  const history = await fetchHistory();

  return (
    <div className="space-y-8 max-w-4xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">종목 검색</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          종목 코드 또는 한글 이름을 입력하면 추세 · 패턴 · 거래량 · 매매플랜
          분석 결과가 표시됩니다.
        </p>
      </header>

      <section className="rounded-xl border border-border bg-card p-5">
        <TickerSearch autoFocus />
      </section>

      {history.length > 0 && (
        <section className="rounded-lg border border-border bg-card p-5">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-medium">최근 검색</h2>
            <ClearHistoryButton />
          </div>
          <ul className="mt-3 flex flex-wrap gap-2">
            {history.map((h, i) => {
              // Prefer the canonical ticker route when we resolved one;
              // otherwise fall back to the raw query so a name-search
              // lands on the same path as a fresh /stocks/[query] hit.
              const href = h.ticker
                ? `/stocks/${encodeURIComponent(h.ticker)}`
                : `/stocks/${encodeURIComponent(h.query)}`;
              return (
                <li key={`${h.created_at}-${i}`}>
                  <Link
                    href={href}
                    className="inline-flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1.5 text-xs hover:bg-muted transition-colors"
                  >
                    <span className="font-medium">{h.query}</span>
                    {h.ticker && h.ticker !== h.query && (
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {h.ticker}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="text-sm font-medium mb-3">티커 입력 규칙</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>
            <span className="font-mono">AAPL</span>,{" "}
            <span className="font-mono">MSFT</span> — 미국 종목 (대소문자 무관)
          </li>
          <li>
            <span className="font-mono">005930.KS</span> — KOSPI 종목 (6자리 +
            .KS)
          </li>
          <li>
            <span className="font-mono">035420.KQ</span> — KOSDAQ 종목 (6자리 +
            .KQ)
          </li>
          <li>
            <span className="font-mono">005930</span> — 6자리만 입력하면 자동
            .KS 추가
          </li>
        </ul>
      </section>
    </div>
  );
}
