"use client";

/**
 * HelpTip — lightweight, dependency-free tooltip / glossary popover.
 *
 * Two usage shapes:
 *
 *   <HelpTip term="ssang_badak" />           // standalone "?" icon
 *   <HelpTip term="ssang_badak">쌍바닥</HelpTip>  // inline, gets dotted underline
 *
 * Falls back to `body`/`title` props if `term` is unknown, so callers can
 * pass ad-hoc explanations too:
 *
 *   <HelpTip title="DAILY" body="일봉 기준 — 매일 캔들 하나로 본 추세." />
 *
 * Triggered on hover, focus, and click (so mobile users can tap). The
 * popover dismisses on outside click, Escape, or blur.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { GLOSSARY, type GlossaryEntry } from "@/lib/glossary";
import { cn } from "@/lib/utils";

type Props = {
  /** Glossary key. If omitted, `title`/`body` are used directly. */
  term?: string;
  /** Override or stand-alone title. */
  title?: string;
  /** Override or stand-alone body. */
  body?: ReactNode;
  /** Optional external "more info" link. */
  link?: { href: string; label?: string };
  /** Inline label to wrap. If omitted, a small "?" icon is rendered. */
  children?: ReactNode;
  /** Popover side relative to trigger. */
  side?: "top" | "bottom";
  className?: string;
};

export function HelpTip({
  term,
  title,
  body,
  link,
  children,
  side = "bottom",
  className,
}: Props) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  const entry: GlossaryEntry | null = term
    ? (GLOSSARY[term] ?? null)
    : null;
  const resolvedTitle = title ?? entry?.title ?? term ?? "";
  const resolvedBody = body ?? entry?.body ?? null;
  const resolvedLink = link ?? entry?.link;

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!resolvedBody && !resolvedLink) {
    // Nothing to show — render plain children (no icon) so the page doesn't
    // get a dead "?" badge for an unknown term.
    return <>{children}</>;
  }

  const triggerCls = children
    ? "underline decoration-dotted decoration-muted-foreground/60 underline-offset-2 cursor-help"
    : "inline-flex items-center justify-center w-4 h-4 rounded-full border border-muted-foreground/40 text-[10px] text-muted-foreground hover:text-foreground hover:border-foreground/60 cursor-help align-middle ml-1";

  return (
    <span
      ref={rootRef}
      className={cn("relative inline-block", className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={(e) => {
          e.preventDefault();
          setOpen((v) => !v);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={triggerCls}
      >
        {children ?? "?"}
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className={cn(
            // bg-card uses --card token defined in globals.css; bg-popover
            // was undefined → looked transparent and let underlying page
            // text bleed through. z-30 keeps the popover above normal
            // page content but below the mobile drawer (z-50) + backdrop
            // (z-40), so opening the drawer occludes any open tooltip.
            "absolute z-30 w-72 max-w-[90vw] rounded-md border border-border bg-card text-card-foreground shadow-xl p-3 text-xs leading-relaxed",
            side === "top"
              ? "bottom-full mb-1 left-0"
              : "top-full mt-1 left-0",
          )}
        >
          <div className="font-medium text-sm text-foreground mb-1">
            {resolvedTitle}
          </div>
          {resolvedBody && (
            <div className="text-muted-foreground whitespace-pre-line">
              {resolvedBody}
            </div>
          )}
          {resolvedLink && (
            <a
              href={resolvedLink.href}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-2 inline-block text-[11px] text-sky-600 dark:text-sky-400 hover:underline"
            >
              {resolvedLink.label ?? "더 알아보기 →"}
            </a>
          )}
        </span>
      )}
    </span>
  );
}
