"use client";

/**
 * Dashboard 'global breaking' news strip.
 *
 * Pulls from /api/news/global (Investing.com + 연합뉴스 merged, 5min ISR).
 * Auto-refreshes every 5 minutes on the client so users who leave the
 * page open get fresh items without a hard reload.
 */
import { useEffect, useState } from "react";

type Item = {
  title: string;
  url: string;
  source: string;
  published_at: string;
};

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  const diffMin = (Date.now() - t) / 60000;
  if (diffMin < 1) return "방금";
  if (diffMin < 60) return `${Math.floor(diffMin)}분 전`;
  if (diffMin < 60 * 24) return `${Math.floor(diffMin / 60)}시간 전`;
  return new Date(iso).toLocaleDateString("ko-KR");
}

export function GlobalNews({ limit = 12 }: { limit?: number }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    function load() {
      fetch("/api/news/global")
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled) setItems((d.items ?? []) as Item[]);
        })
        .catch((e) => {
          if (!cancelled) setError(String(e));
        });
    }
    load();
    const id = setInterval(load, 5 * 60 * 1000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <header className="flex items-center justify-between mb-3">
        <div>
          <div className="text-xs uppercase tracking-widest text-muted-foreground">
            글로벌 속보
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground/70">
            Investing.com · 연합뉴스 · 5분마다 자동 갱신
          </div>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-3 text-sm text-rose-700 dark:text-rose-300">
          속보를 불러오지 못했습니다. ({error})
        </div>
      ) : items === null ? (
        <div className="rounded-md border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
          속보 불러오는 중…
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-md border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
          속보가 없습니다.
        </div>
      ) : (
        <ul className="divide-y divide-border rounded-md border border-border">
          {items.slice(0, limit).map((n, i) => (
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
                  <span className="font-medium">{n.source}</span>
                  <span suppressHydrationWarning>
                    {timeAgo(n.published_at)}
                  </span>
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
