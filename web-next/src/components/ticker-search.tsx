"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";

const EXAMPLES_US = ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA"];
const EXAMPLES_KR = ["005930.KS", "035720.KS", "035420.KS", "000660.KS"];

interface Suggestion {
  ticker: string;
  name: string;
  market: string;
  sector: string | null;
}

export function TickerSearch({ autoFocus = false }: { autoFocus?: boolean }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  // Debounced fetch — only runs while user is actively typing something.
  const trimmed = q.trim();
  useEffect(() => {
    if (trimmed.length < 1) return;
    let cancelled = false;
    const id = setTimeout(async () => {
      try {
        const r = await fetch(`/api/search?q=${encodeURIComponent(trimmed)}&limit=10`);
        if (!r.ok) return;
        const data = await r.json();
        if (!cancelled) {
          setSuggestions(data.items ?? []);
          setActiveIdx(-1);
        }
      } catch {
        /* ignore */
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [trimmed]);

  // Derived: when the query is empty, suggestions should appear empty.
  const visibleSuggestions = trimmed.length < 1 ? [] : suggestions;

  // Click outside closes dropdown
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // ASCII letters / digits / dot / dash only — Korean characters fail.
  const CANONICAL_TICKER_RE = /^[A-Z0-9.\-]+$/;

  const submit = async (raw: string) => {
    const t = raw.trim();
    if (!t) return;

    // 6-digit Korean code → assume KS.
    if (/^\d{6}$/.test(t)) {
      setOpen(false);
      router.push(`/stocks/${t}.KS`);
      return;
    }

    const upper = t.toUpperCase();

    // Already canonical (ASCII)? Navigate directly.
    if (CANONICAL_TICKER_RE.test(upper)) {
      setOpen(false);
      router.push(`/stocks/${encodeURIComponent(upper)}`);
      return;
    }

    // Otherwise it's a Korean name or free-form query. Resolve via search
    // API first so we never push a non-canonical ticker into the URL —
    // that would 400 the watchlist endpoint.
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(t)}&limit=1`);
      if (r.ok) {
        const data = await r.json();
        const first = (data.items ?? [])[0];
        if (first?.ticker) {
          setOpen(false);
          router.push(`/stocks/${encodeURIComponent(first.ticker)}`);
          return;
        }
      }
    } catch {
      /* fall through */
    }

    // No match found — still navigate so the detail page can show a
    // friendly "not found" message.
    setOpen(false);
    router.push(`/stocks/${encodeURIComponent(t)}`);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || visibleSuggestions.length === 0) {
      if (e.key === "Enter") submit(q);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, visibleSuggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIdx >= 0) submit(visibleSuggestions[activeIdx].ticker);
      else submit(q);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="space-y-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (activeIdx >= 0 && visibleSuggestions[activeIdx]) {
            submit(visibleSuggestions[activeIdx].ticker);
          } else {
            submit(q);
          }
        }}
      >
        <div className="relative flex-1 max-w-md" ref={wrapperRef}>
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <input
            autoFocus={autoFocus}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOpen(true);
            }}
            onFocus={() => q && setOpen(true)}
            onKeyDown={onKeyDown}
            placeholder="삼성전자, AAPL, 005930 …"
            className="w-full pl-9 pr-3 py-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30"
            autoComplete="off"
            data-testid="search-input"
          />
          {open && visibleSuggestions.length > 0 && (
            <ul
              role="listbox"
              data-testid="search-suggestions"
              className="absolute z-20 mt-1 w-full max-h-72 overflow-auto rounded-md border border-border bg-card shadow-lg"
            >
              {visibleSuggestions.map((s, i) => (
                <li
                  key={s.ticker}
                  role="option"
                  aria-selected={i === activeIdx}
                  onMouseEnter={() => setActiveIdx(i)}
                  onMouseDown={(e) => {
                    e.preventDefault();   // prevent input blur before click
                    submit(s.ticker);
                  }}
                  className={`px-3 py-2 cursor-pointer flex items-baseline gap-3 text-sm ${
                    i === activeIdx ? "bg-muted" : "hover:bg-muted/60"
                  }`}
                >
                  <span className="font-mono text-xs text-foreground/80 w-24 truncate">
                    {s.ticker}
                  </span>
                  <span className="flex-1 truncate">{s.name}</span>
                  <span className="text-xs text-muted-foreground">{s.market}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 transition"
        >
          분석
        </button>
      </form>

      <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
        <span>예시 (US):</span>
        {EXAMPLES_US.map((t) => (
          <button
            key={t}
            onClick={() => submit(t)}
            className="px-2 py-1 rounded border border-border hover:bg-muted font-mono"
          >
            {t}
          </button>
        ))}
        <span className="ml-3">예시 (KR):</span>
        {EXAMPLES_KR.map((t) => (
          <button
            key={t}
            onClick={() => submit(t)}
            className="px-2 py-1 rounded border border-border hover:bg-muted font-mono"
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  );
}
