"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Search } from "lucide-react";

const EXAMPLES_US = ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA"];
const EXAMPLES_KR = ["005930.KS", "035720.KS", "035420.KS", "000660.KS"];

export function TickerSearch({ autoFocus = false }: { autoFocus?: boolean }) {
  const router = useRouter();
  const [q, setQ] = useState("");

  const submit = (raw: string) => {
    const t = raw.trim();
    if (!t) return;
    // Normalize: uppercase US; KR 6-digit gets .KS by default
    let ticker = t.toUpperCase();
    if (/^\d{6}$/.test(t)) ticker = `${t}.KS`;
    router.push(`/stocks/${encodeURIComponent(ticker)}`);
  };

  return (
    <div className="space-y-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit(q);
        }}
      >
        <div className="relative flex-1 max-w-md">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <input
            autoFocus={autoFocus}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="AAPL, 005930.KS, 005930 …"
            className="w-full pl-9 pr-3 py-2 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30"
          />
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
