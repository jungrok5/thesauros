/**
 * Last-close quote card. Source is the latest weekly bar from `bars`
 * (granularity='W') — NOT a live intraday tick. The book is explicit
 * (p238-241) that intraday prices aren't decision-grade, so the site
 * stays close-only.
 *
 * Daily bars (`bars_daily`) were dropped in migration 021 (weekly
 * pivot); the /api/quote route now reads from `bars` directly.
 */
"use client";

import { useEffect, useState } from "react";
import { priceLabelFor, classifySession } from "@/lib/market-session";

interface Quote {
  ticker: string;
  as_of: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  source: string;
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

export function LastClose({ ticker }: Props) {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
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
    // No live polling — daily-close source, refresh once per request.
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  if (loading)
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
        시세 로드 중...
      </div>
    );
  if (error || !quote)
    return null;   // hide quietly when no data exists yet for this ticker

  const isUp = (quote.change ?? 0) > 0;
  const isDown = (quote.change ?? 0) < 0;
  const tone = isUp
    ? "text-rose-500"
    : isDown
      ? "text-blue-500"
      : "text-muted-foreground";

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <div className="text-xs text-muted-foreground">
            {priceLabelFor(ticker, quote.as_of)} ({quote.as_of})
            {classifySession(ticker, quote.as_of) === "intraday" && (
              <span className="ml-1 text-amber-700 dark:text-amber-300">
                · 장중
              </span>
            )}
          </div>
          <div className="mt-1 flex items-baseline gap-2 flex-wrap">
            <span className="text-2xl font-mono">{fmt(quote.price, 2)}</span>
            <span className={`font-mono text-sm ${tone}`}>
              {(quote.change ?? 0) >= 0 ? "+" : ""}
              {fmt(quote.change, 2)}
            </span>
            <span className={`font-mono text-sm ${tone}`}>
              (
              {quote.change_pct != null
                ? `${quote.change_pct.toFixed(2)}%`
                : "—"}
              )
            </span>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-x-2 sm:gap-x-4 text-xs text-muted-foreground">
          <div>시 {fmt(quote.open, 2)}</div>
          <div>고 {fmt(quote.high, 2)}</div>
          <div>저 {fmt(quote.low, 2)}</div>
          <div className="col-span-3">거래량 {fmt(quote.volume)}</div>
        </div>
      </div>
    </div>
  );
}
