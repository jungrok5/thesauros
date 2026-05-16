"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  ticker: string;
  initiallyAdded?: boolean;
  initialCategory?: "observing" | "holding";
}

export function WatchlistButton({
  ticker,
  initiallyAdded = false,
  initialCategory = "observing",
}: Props) {
  const [added, setAdded] = useState(initiallyAdded);
  const [category, setCategory] = useState<"observing" | "holding">(
    initialCategory,
  );
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function toggle(nextCategory: "observing" | "holding") {
    if (busy) return;
    setBusy(true);
    try {
      if (added && nextCategory === category) {
        // remove
        const r = await fetch(
          `/api/watchlist?ticker=${encodeURIComponent(ticker)}`,
          { method: "DELETE" },
        );
        if (!r.ok) throw new Error(String(r.status));
        setAdded(false);
      } else {
        // upsert
        const r = await fetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker, category: nextCategory }),
        });
        if (!r.ok) throw new Error(String(r.status));
        setAdded(true);
        setCategory(nextCategory);
      }
      router.refresh();
    } catch (e) {
      alert(`실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inline-flex items-center gap-2" data-testid="watchlist-button">
      <button
        type="button"
        onClick={() => toggle("observing")}
        disabled={busy}
        data-testid="watchlist-observing"
        className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${
          added && category === "observing"
            ? "bg-foreground text-background border-foreground"
            : "bg-background border-input hover:bg-muted"
        }`}
      >
        {added && category === "observing" ? "✓ 관찰 중" : "+ 관찰"}
      </button>
      <button
        type="button"
        onClick={() => toggle("holding")}
        disabled={busy}
        data-testid="watchlist-holding"
        className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${
          added && category === "holding"
            ? "bg-emerald-600 text-white border-emerald-600"
            : "bg-background border-input hover:bg-muted"
        }`}
      >
        {added && category === "holding" ? "✓ 보유 중" : "+ 보유"}
      </button>
    </div>
  );
}
