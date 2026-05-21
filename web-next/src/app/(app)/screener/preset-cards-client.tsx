/**
 * Preset chooser cards — client component so the active card switches
 * INSTANTLY on click (reading the URL via useSearchParams) instead of
 * waiting for the server round-trip + RPC fetch to finish.
 *
 * Result section below is server-rendered with the new searchParams —
 * sees its own update once Next.js streams the new RSC payload. Until
 * then the previous result stays visible (default RSC behavior).
 * useTransition surfaces an isPending overlay on top of the existing
 * result so users see "loading new preset" without losing context.
 *
 * Why this exists: user feedback (2026-05-21) — "스크리너 타입 누르면
 * 반응이 한참 뒤에 와. 먼저 선택되고 뒤늦게 내용이 채워져도 되잖아".
 * Server component path was: click → URL change → full RSC re-render
 * blocks the preset chip's `active` state from updating until the new
 * data arrives. Client component breaks that coupling.
 */
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";
import type { ScreenerPreset } from "@/lib/screener-presets";

export function PresetCardsClient({
  presets,
}: {
  presets: readonly ScreenerPreset[];
}) {
  const router = useRouter();
  const sp = useSearchParams();
  const activeSlug = sp.get("preset");
  const [isPending, startTransition] = useTransition();

  function handleClick(e: React.MouseEvent, slug: string) {
    // Let middle-click / cmd-click open new tab.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    startTransition(() => {
      router.push(`/screener?preset=${slug}`);
    });
  }

  return (
    <>
      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {presets.map((p) => {
          const active = activeSlug === p.slug;
          return (
            <Link
              key={p.slug}
              href={`/screener?preset=${p.slug}`}
              onClick={(e) => handleClick(e, p.slug)}
              className={`rounded-lg border-2 p-4 transition-colors ${
                active
                  ? "border-foreground bg-accent"
                  : "border-border bg-card hover:bg-accent/40"
              } ${isPending && active ? "animate-pulse" : ""}`}
              prefetch
              aria-pressed={active}
            >
              <div className="flex items-baseline gap-2 mb-1">
                <span className="text-lg">{p.emoji}</span>
                <h2 className="text-sm font-semibold">{p.title}</h2>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {p.oneLiner}
              </p>
            </Link>
          );
        })}
      </section>
      {isPending && (
        <div
          className="text-xs text-muted-foreground flex items-center gap-2"
          role="status"
          aria-live="polite"
        >
          <span className="inline-block w-3 h-3 rounded-full border-2 border-muted-foreground border-t-transparent animate-spin" />
          새 검색 결과 불러오는 중…
        </div>
      )}
    </>
  );
}
