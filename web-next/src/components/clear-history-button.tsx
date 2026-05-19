"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

export function ClearHistoryButton() {
  const router = useRouter();
  const [pending, start] = useTransition();
  return (
    <button
      type="button"
      disabled={pending}
      onClick={() =>
        start(async () => {
          await fetch("/api/search-history", { method: "DELETE" });
          router.refresh();
        })
      }
      className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50"
      data-testid="clear-search-history"
    >
      {pending ? "지우는 중…" : "전체 지우기"}
    </button>
  );
}
