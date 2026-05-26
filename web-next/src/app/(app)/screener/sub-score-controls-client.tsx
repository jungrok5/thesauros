/**
 * Sub-score chip row (filters + 2nd sort + buy_only toggle) — client
 * component so chips switch INSTANTLY on click instead of waiting for
 * the server RPC round-trip to finish. Same pattern as PresetCardsClient.
 *
 * Reads its state from the URL (useSearchParams) so it stays in sync
 * with the server-rendered result list. useTransition surfaces an
 * isPending hint while new data streams in.
 *
 * (2026-05-21 — applied same instant-active + pending pattern as
 *  PresetCardsClient + ThemeSortChipsClient.)
 */
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";

type FilterChipProps = {
  href: string;
  active: boolean;
  title?: string;
  isPending: boolean;
  onClick: (e: React.MouseEvent, href: string) => void;
  children: React.ReactNode;
};

function FilterChip({ href, active, title, isPending, onClick, children }: FilterChipProps) {
  return (
    <Link
      href={href}
      title={title}
      onClick={(e) => onClick(e, href)}
      aria-pressed={active}
      className={
        "rounded-full border px-2 py-0.5 transition-colors " +
        (active
          ? "border-foreground/40 bg-foreground/10 text-foreground"
          : "border-border bg-card text-muted-foreground hover:bg-muted") +
        (isPending && active ? " animate-pulse" : "")
      }
    >
      {children}
    </Link>
  );
}

export function SubScoreControlsClient({ preset }: { preset: string }) {
  const router = useRouter();
  const sp = useSearchParams();
  const [isPending, startTransition] = useTransition();

  // Read state directly from URL — always in sync with the rendered list.
  // 2026-05-26: sort2 + buy_only chips removed (single book-spirit sort
  // is canonical). The URL keys are silently ignored by the server route
  // so old bookmarks don't 404.
  const volSurge = sp.get("vol_surge") === "1";
  const zone = sp.get("zone");
  const catalystMax = sp.get("catalyst_max")
    ? Number(sp.get("catalyst_max"))
    : null;

  function url(overrides: Record<string, string | null>): string {
    const params = new URLSearchParams();
    params.set("preset", preset);
    if (volSurge) params.set("vol_surge", "1");
    if (zone) params.set("zone", zone);
    if (catalystMax != null) params.set("catalyst_max", String(catalystMax));
    for (const [k, v] of Object.entries(overrides)) {
      if (v == null) params.delete(k);
      else params.set(k, v);
    }
    return `/screener?${params.toString()}`;
  }

  function go(e: React.MouseEvent, href: string) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    startTransition(() => {
      router.push(href);
    });
  }

  return (
    <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
      <span className="text-muted-foreground mr-1">필터:</span>
      <FilterChip
        href={url({ vol_surge: volSurge ? null : "1" })}
        active={volSurge}
        isPending={isPending}
        onClick={go}
        title="거래량 case 3 (바닥 폭증) + case 9 (급등 양봉) 만"
      >
        📊 거래량 폭증
      </FilterChip>
      <FilterChip
        href={url({ zone: zone === "safe75" ? null : "safe75" })}
        active={zone === "safe75"}
        isPending={isPending}
        onClick={go}
        title="4등분선 75% 안전지대"
      >
        🎯 safe75
      </FilterChip>
      <FilterChip
        href={url({ zone: zone === "warn50" ? null : "warn50" })}
        active={zone === "warn50"}
        isPending={isPending}
        onClick={go}
        title="4등분선 50% 경계"
      >
        🎯 warn50
      </FilterChip>
      <FilterChip
        href={url({ catalyst_max: catalystMax === 4 ? null : "4" })}
        active={catalystMax === 4}
        isPending={isPending}
        onClick={go}
        title="장대양봉 catalyst 4주 이내 종목만"
      >
        🔥 catalyst 4주 이내
      </FilterChip>
      {isPending && (
        <span
          className="text-muted-foreground inline-flex items-center gap-1 ml-1"
          role="status"
          aria-live="polite"
        >
          <span className="inline-block w-3 h-3 rounded-full border-2 border-muted-foreground border-t-transparent animate-spin" />
          적용 중…
        </span>
      )}
    </div>
  );
}
