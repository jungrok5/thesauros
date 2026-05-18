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

type Resp = { items: Item[]; supported?: boolean };

export function NewsTabClient({ ticker }: { ticker: string }) {
  const [resp, setResp] = useState<Resp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Reset stale state on ticker change so the loading skeleton renders
    // while the new fetch is in flight. Cascading-render warning from
    // the strict rule is acceptable here — the alternative (keep stale
    // data until new arrives) shows the previous ticker's news briefly.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setError(null);
    setResp(null);
    fetch(`/api/news/${encodeURIComponent(ticker)}`)
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        setResp({
          items: (data.items ?? []) as Item[],
          supported: data.supported !== false,
        });
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
  if (resp === null) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        뉴스 불러오는 중…
      </div>
    );
  }
  if (!resp.supported) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        이 종목은 현재 뉴스 자동 수집 대상이 아닙니다. (네이버 증권 종목 뉴스 = 한국 종목 한정)
      </div>
    );
  }
  const items = resp.items;
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        관련 뉴스가 없습니다.
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
