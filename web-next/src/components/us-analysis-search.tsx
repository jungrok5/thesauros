"use client";

import { useState } from "react";

interface AnalysisResult {
  ticker: string;
  fetched_now: boolean;
  bars_count: number;
  first_bar: string;
  last_bar: string;
  meta: { name?: string | null; exchange?: string | null; description?: string | null };
  analysis: {
    last_close?: number;
    action?: string;
    book_score?: number;
    trend?: {
      weekly?: { ma_240?: number | null; book_signal?: string };
      monthly?: { ma_240?: number | null; book_signal?: string };
    };
    patterns?: Array<{
      kind: string;
      timeframe: string;
      direction: string;
      confidence: number;
      completed: boolean;
    }>;
    volume_case?: { case: number; label_kr: string; direction: string };
  };
}

const POPULAR = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "META", "AMZN"];

export function UsAnalysisSearch() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(ev?: React.FormEvent) {
    ev?.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await fetch(`/api/us-analysis?ticker=${encodeURIComponent(t)}`, {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        throw new Error(body.error || `HTTP ${r.status}`);
      }
      setResult(body as AnalysisResult);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex gap-2">
        <input
          type="text"
          inputMode="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="e.g. AAPL, NVDA, TSLA"
          className="flex-1 rounded-md border border-border bg-background px-3 py-2 font-mono uppercase"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={loading || !ticker.trim()}
          className="rounded-md bg-foreground text-background px-4 py-2 font-medium disabled:opacity-50"
        >
          {loading ? "분석 중…" : "분석"}
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        인기 검색:
        {POPULAR.map((t) => (
          <button
            key={t}
            onClick={() => {
              setTicker(t);
              setTimeout(() => submit(), 0);
            }}
            className="font-mono px-1.5 py-0.5 rounded border border-border hover:bg-muted"
          >
            {t}
          </button>
        ))}
      </div>

      {loading && (
        <div className="rounded-md border border-sky-500/40 bg-sky-500/5 p-3 text-sm">
          <span className="text-sky-700 dark:text-sky-300">
            🔄 Tiingo fetch + 책 분석 진행 중 (~3-5초)…
          </span>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-3 text-sm">
          <span className="text-rose-700 dark:text-rose-300">❌ {error}</span>
        </div>
      )}

      {result && <AnalysisCard result={result} />}
    </div>
  );
}

function AnalysisCard({ result }: { result: AnalysisResult }) {
  const a = result.analysis;
  const trendW = a.trend?.weekly;
  const lastClose = a.last_close;
  const ma240 = trendW?.ma_240;
  const aboveMA = lastClose && ma240 ? lastClose > ma240 : null;
  const bullishPatterns = (a.patterns || []).filter(
    (p) => p.completed && p.direction === "bullish",
  );
  const bearishPatterns = (a.patterns || []).filter(
    (p) => p.completed && p.direction === "bearish",
  );

  return (
    <section className="rounded-lg border border-border bg-card p-4 space-y-4">
      <header className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-mono text-lg">{result.ticker}</span>
          {result.meta.name && (
            <span className="text-lg font-medium">{result.meta.name}</span>
          )}
          {result.meta.exchange && (
            <span className="text-xs text-muted-foreground border border-border rounded px-1.5 py-0.5">
              {result.meta.exchange}
            </span>
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {result.bars_count} weekly bars ({result.first_bar} → {result.last_bar})
          {result.fetched_now ? " · 방금 fetch" : " · 캐시"}
        </span>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="현재가" value={lastClose ? `$${lastClose.toFixed(2)}` : "—"} />
        <Stat label="240MA (주봉)" value={ma240 ? `$${ma240.toFixed(2)}` : "—"} />
        <Stat
          label="240MA 위?"
          value={aboveMA == null ? "—" : aboveMA ? "✅ YES" : "❌ NO"}
          accent={aboveMA === true}
          negative={aboveMA === false}
        />
        <Stat
          label="book_score"
          value={a.book_score != null ? a.book_score.toFixed(2) : "—"}
          accent={(a.book_score ?? 0) > 0.3}
          negative={(a.book_score ?? 0) < -0.3}
        />
      </div>

      <div className="text-sm">
        <div className="font-medium mb-1">trend signal</div>
        <div className="text-muted-foreground">
          weekly: {trendW?.book_signal || "—"} · monthly:{" "}
          {a.trend?.monthly?.book_signal || "—"}
        </div>
      </div>

      {bullishPatterns.length > 0 && (
        <div className="text-sm">
          <div className="font-medium mb-1 text-emerald-600 dark:text-emerald-400">
            🟢 완성된 강세 패턴 ({bullishPatterns.length})
          </div>
          <ul className="space-y-0.5 text-muted-foreground">
            {bullishPatterns.map((p, i) => (
              <li key={i}>
                {p.kind} ({p.timeframe}, 신뢰도 {p.confidence.toFixed(2)})
              </li>
            ))}
          </ul>
        </div>
      )}

      {bearishPatterns.length > 0 && (
        <div className="text-sm">
          <div className="font-medium mb-1 text-rose-600 dark:text-rose-400">
            🔴 완성된 약세 패턴 ({bearishPatterns.length})
          </div>
          <ul className="space-y-0.5 text-muted-foreground">
            {bearishPatterns.map((p, i) => (
              <li key={i}>
                {p.kind} ({p.timeframe}, 신뢰도 {p.confidence.toFixed(2)})
              </li>
            ))}
          </ul>
        </div>
      )}

      {a.volume_case && (
        <div className="text-sm">
          <div className="font-medium mb-1">거래량 케이스 #{a.volume_case.case}</div>
          <div className="text-muted-foreground">
            {a.volume_case.label_kr} ({a.volume_case.direction})
          </div>
        </div>
      )}
    </section>
  );
}

function Stat({
  label, value, accent, negative,
}: {
  label: string;
  value: string;
  accent?: boolean;
  negative?: boolean;
}) {
  const tone = accent
    ? "text-emerald-600 dark:text-emerald-400"
    : negative
    ? "text-rose-600 dark:text-rose-400"
    : "text-foreground";
  return (
    <div className="rounded-md border border-border p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 font-semibold ${tone} tabular-nums`}>{value}</div>
    </div>
  );
}
