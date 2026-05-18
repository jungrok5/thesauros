"use client";

/**
 * Realtime market ribbon — KOSPI / KOSDAQ / S&P / NASDAQ / VIX / 환율 /
 * 美10Y / WTI / Gold / BTC. Polls /api/quotes/realtime every 60s.
 *
 * Replaces the dashboard's stale-by-cron indices view. The slow macro
 * cards below remain cron-fed (CPI / PPI / M2 / 실업률 etc.) because
 * those genuinely only move on monthly/quarterly schedules.
 */
import { useEffect, useState } from "react";

type Quote = {
  symbol: string;
  label: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  as_of: number | null;
};

function fmt(price: number | null, symbol: string): string {
  if (price == null) return "—";
  // KOSPI / KOSDAQ — Korean indices use integer-ish display
  if (symbol === "^KS11" || symbol === "^KQ11") {
    return price.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
  }
  if (symbol === "KRW=X") {
    return price.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  }
  if (symbol === "BTC-USD") {
    return price.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  return price.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function staleLabel(asOf: number | null): string | null {
  if (!asOf) return null;
  const ageMin = (Date.now() / 1000 - asOf) / 60;
  if (ageMin < 5) return null;          // fresh
  if (ageMin < 60) return `${Math.floor(ageMin)}m`;
  if (ageMin < 60 * 24) return `${Math.floor(ageMin / 60)}h`;
  return `${Math.floor(ageMin / (60 * 24))}d`;
}

export function MarketTicker() {
  const [quotes, setQuotes] = useState<Quote[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    function load() {
      fetch("/api/quotes/realtime")
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled) setQuotes((d.items ?? []) as Quote[]);
        })
        .catch(() => {/* keep last good */});
    }
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <section className="rounded-xl border border-border bg-card p-3">
      <div className="overflow-x-auto -mx-1 px-1">
        <div className="flex items-stretch gap-1 min-w-max">
          {(quotes ?? Array(11).fill(null)).map((q, i) => (
            <Tile key={q?.symbol ?? i} q={q} />
          ))}
        </div>
      </div>
      <div className="mt-2 text-[10px] text-muted-foreground/70 text-right">
        Yahoo Finance · 1분마다 자동 갱신 · 시장 휴장 시 마지막 종가
      </div>
    </section>
  );
}

function Tile({ q }: { q: Quote | null }) {
  if (!q) {
    return (
      <div className="min-w-[110px] rounded-md border border-border bg-background/40 p-2">
        <div className="text-[11px] text-muted-foreground">—</div>
        <div className="mt-1 text-sm font-mono">…</div>
      </div>
    );
  }
  const pct = q.change_pct;
  const up = pct != null && pct > 0;
  const dn = pct != null && pct < 0;
  const tone =
    up ? "text-rose-600 dark:text-rose-400"    // KR convention: up = red
      : dn ? "text-sky-600 dark:text-sky-400"  // down = blue
        : "text-muted-foreground";
  const stale = staleLabel(q.as_of);
  return (
    <div className="min-w-[110px] rounded-md border border-border bg-background/40 p-2">
      <div className="text-[11px] text-muted-foreground flex items-center justify-between">
        <span>{q.label}</span>
        {stale && <span className="text-[9px] opacity-60">{stale}</span>}
      </div>
      <div className="mt-1 text-sm font-mono">{fmt(q.price, q.symbol)}</div>
      <div className={`text-[11px] font-mono ${tone}`}>
        {pct == null
          ? "—"
          : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
      </div>
    </div>
  );
}
