"use client";

/**
 * Realtime market ribbon — KOSPI / KOSDAQ / S&P / NASDAQ / VIX / 환율 /
 * 美10Y / WTI / Gold / BTC. Polls /api/quotes/realtime every 60s.
 *
 * Layout adapts to viewport — mobile uses a 2-column grid so users
 * don't have to horizontal-scroll through 11 tiles; md+ keeps the
 * original ribbon shape so the whole snapshot fits in one row.
 * Each tile includes a ~1mo sparkline (sparkline data lives on the
 * same API response — no extra fetch).
 */
import { useEffect, useState } from "react";
import { Sparkline } from "@/components/sparkline";
import { tickerHint } from "@/lib/macro-interpret";

type Quote = {
  symbol: string;
  label: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  as_of: number | null;
  sparkline: number[] | null;
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

  const items = quotes ?? Array(11).fill(null);
  return (
    <section className="rounded-xl border border-border bg-card p-3">
      {/* Mobile (< sm): 2-col grid — vertical scroll is fine, easier
          to scan than a long horizontal one. md+: original ribbon */}
      <div className="grid grid-cols-2 gap-1.5 sm:hidden">
        {items.map((q, i) => (
          <Tile key={q?.symbol ?? i} q={q} variant="grid" />
        ))}
      </div>
      <div className="hidden sm:block overflow-x-auto -mx-1 px-1">
        <div className="flex items-stretch gap-1 min-w-max">
          {items.map((q, i) => (
            <Tile key={q?.symbol ?? i} q={q} variant="row" />
          ))}
        </div>
      </div>
      <div className="mt-2 text-[10px] text-muted-foreground/70 text-right">
        Yahoo Finance · 1분마다 자동 갱신 · 시장 휴장 시 마지막 종가
      </div>
    </section>
  );
}

function Tile({
  q,
  variant,
}: {
  q: Quote | null;
  variant: "grid" | "row";
}) {
  // Grid (mobile) wants full container width; row (desktop) wants
  // fixed compact width so the ribbon stays predictable.
  const widthCls = variant === "grid"
    ? "w-full"
    : "min-w-[120px] sm:min-w-[132px]";

  if (!q) {
    return (
      <div className={`${widthCls} rounded-md border border-border bg-background/40 p-2`}>
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
  // Match the sparkline stroke to the tile's tone (KR red/blue).
  const sparkColor = up ? "#dc2626" : dn ? "#2563eb" : "#94a3b8";
  const stale = staleLabel(q.as_of);
  return (
    <div className={`${widthCls} rounded-md border border-border bg-background/40 p-2`}>
      <div className="text-[11px] text-muted-foreground flex items-center justify-between">
        <span className="truncate">{q.label}</span>
        {stale && <span className="text-[9px] opacity-60 shrink-0">{stale}</span>}
      </div>
      <div className="mt-1 flex items-center justify-between gap-1">
        <div>
          <div className="text-sm font-mono leading-tight">{fmt(q.price, q.symbol)}</div>
          <div className={`text-[11px] font-mono ${tone} leading-tight`}>
            {pct == null
              ? "—"
              : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
          </div>
        </div>
        {q.sparkline && q.sparkline.length >= 2 && (
          <Sparkline
            closes={q.sparkline}
            width={variant === "grid" ? 56 : 48}
            height={26}
            color={sparkColor}
          />
        )}
      </div>
      {/* Static "이 지표 ↑ → 주식 ↑/↓" hint for non-index tickers
          (VIX/유가/금/달러 등). Indices skip this — interpreting their
          own move against \"the stock market\" is tautological. */}
      {(() => {
        const hint = tickerHint(q.symbol);
        return hint ? (
          <div className="mt-1 text-[10px] text-muted-foreground/80 leading-snug">
            💡 {hint}
          </div>
        ) : null;
      })()}
    </div>
  );
}
