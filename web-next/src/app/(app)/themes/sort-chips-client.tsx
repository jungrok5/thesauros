/**
 * Theme list sort chips — client component so the active chip switches
 * INSTANTLY on click (reading the URL via useSearchParams) + isPending
 * spinner while the server re-renders the new sorted list.
 *
 * Same pattern as /screener PresetCardsClient (2026-05-21).
 */
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTransition } from "react";
import { cn } from "@/lib/utils";

const SORT_LABELS = [
  { key: "hot",  label: "🔥 핫",       hint: "평균 등락률 + 강매수 비중" },
  { key: "up",   label: "🟢 상승",     hint: "평균 등락률 높은 순" },
  { key: "down", label: "🔴 하락",     hint: "평균 등락률 낮은 순" },
  { key: "buys", label: "💡 매수 우위", hint: "강매수+매수 종목 많은 순" },
  { key: "size", label: "📦 종목수",   hint: "종목 수 많은 순" },
] as const;

export function ThemeSortChipsClient() {
  const router = useRouter();
  const sp = useSearchParams();
  const active = (sp.get("sort") as (typeof SORT_LABELS)[number]["key"]) ?? "hot";
  const [isPending, startTransition] = useTransition();

  function handleClick(e: React.MouseEvent, key: string) {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    startTransition(() => {
      router.push(key === "hot" ? "/themes" : `/themes?sort=${key}`);
    });
  }

  return (
    <div className="flex items-center gap-2 flex-wrap text-xs">
      <span className="text-muted-foreground">정렬:</span>
      {SORT_LABELS.map((s) => (
        <Link
          key={s.key}
          href={s.key === "hot" ? "/themes" : `/themes?sort=${s.key}`}
          onClick={(e) => handleClick(e, s.key)}
          title={s.hint}
          className={cn(
            "rounded-full border px-2.5 py-1 transition-colors",
            active === s.key
              ? "border-foreground/30 bg-foreground/5 text-foreground"
              : "border-border bg-card text-muted-foreground hover:bg-muted",
            isPending && active === s.key ? "animate-pulse" : "",
          )}
          aria-pressed={active === s.key}
        >
          {s.label}
        </Link>
      ))}
      {isPending && (
        <span
          className="text-muted-foreground inline-flex items-center gap-1"
          role="status"
          aria-live="polite"
        >
          <span className="inline-block w-3 h-3 rounded-full border-2 border-muted-foreground border-t-transparent animate-spin" />
          정렬 중…
        </span>
      )}
    </div>
  );
}
