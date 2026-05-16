"use client";

import { useEffect, useState } from "react";

interface Quote {
  ticker: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  volume: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  market_cap: number | null;
  per: number | null;
  pbr: number | null;
}

interface Props {
  ticker: string;
}

function fmt(n: number | null | undefined, digits = 0): string {
  if (n == null || !isFinite(n)) return "—";
  return n.toLocaleString("ko-KR", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function LiveQuote({ ticker }: Props) {
  // Only KR tickers get a live quote (KIS API limitation).
  const isKR = /\.(KS|KQ)$/i.test(ticker);

  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Skip the loading state entirely for non-KR tickers (no fetch).
  const [loading, setLoading] = useState(isKR);

  useEffect(() => {
    if (!isKR) return;
    let cancelled = false;
    const fetchQuote = async () => {
      try {
        const r = await fetch(`/api/quote/${encodeURIComponent(ticker)}`, {
          cache: "no-store",
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = (await r.json()) as Quote;
        if (!cancelled) {
          setQuote(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchQuote();
    const id = setInterval(fetchQuote, 30_000);   // 30s refresh
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ticker, isKR]);

  if (!isKR) return null;
  if (loading)
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
        현재가 로드 중...
      </div>
    );
  if (error || !quote)
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
        KIS 현재가 없음 ({error ?? "no data"})
      </div>
    );

  const isUp = (quote.change ?? 0) > 0;
  const isDown = (quote.change ?? 0) < 0;
  const tone = isUp ? "text-rose-500" : isDown ? "text-blue-500" : "text-muted-foreground";

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <div className="text-xs text-muted-foreground">실시간 현재가 (KIS, 모의)</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-mono">{fmt(quote.price)}원</span>
            <span className={`font-mono text-sm ${tone}`}>
              {(quote.change ?? 0) >= 0 ? "+" : ""}
              {fmt(quote.change)}
            </span>
            <span className={`font-mono text-sm ${tone}`}>
              ({quote.change_pct != null ? `${(quote.change_pct).toFixed(2)}%` : "—"})
            </span>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-x-4 text-xs text-muted-foreground">
          <div>시 {fmt(quote.open)}</div>
          <div>고 {fmt(quote.high)}</div>
          <div>저 {fmt(quote.low)}</div>
          <div>거래량 {fmt(quote.volume)}</div>
          <div>PER {quote.per != null ? quote.per.toFixed(2) : "—"}</div>
          <div>PBR {quote.pbr != null ? quote.pbr.toFixed(2) : "—"}</div>
        </div>
      </div>
    </div>
  );
}
