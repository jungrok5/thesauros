"use client";

/**
 * Lazy-loaded news list — fetches `/api/news/[ticker]` on mount. Because
 * the parent <StockTabs> only mounts the active tab's content, the Naver
 * Finance request fires exactly when the user opens the 뉴스 tab, not
 * eagerly on every stock pageview.
 */
import { useEffect, useState } from "react";

type Item = {
  title: string;
  url: string;
  source: string | null;
  published_at: string | null;
};

export function NewsTabClient({ ticker }: { ticker: string }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setItems(null);
    fetch(`/api/news/${encodeURIComponent(ticker)}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        setItems((data.items ?? []) as Item[]);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  if (error) {
    return (
      <div className="rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-700 dark:text-rose-300">
        뉴스를 불러오지 못했습니다. ({error})
      </div>
    );
  }
  if (items === null) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        뉴스 불러오는 중…
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        관련 뉴스가 없습니다. (네이버 증권 종목 뉴스 기준, 한국 종목만 지원)
      </div>
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {items.map((n, i) => (
        <li
          key={`${n.url}-${i}`}
          className="p-3 hover:bg-muted/30 transition-colors"
        >
          <a
            href={n.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block group"
          >
            <div className="text-sm group-hover:text-foreground transition-colors">
              {n.title}
            </div>
            <div className="mt-1 text-xs text-muted-foreground flex gap-3">
              <span>{n.source ?? "—"}</span>
              <span>
                {n.published_at
                  ? new Date(n.published_at).toLocaleDateString("ko-KR")
                  : "—"}
              </span>
            </div>
          </a>
        </li>
      ))}
    </ul>
  );
}
