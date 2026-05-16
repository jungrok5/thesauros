"use client";

import { useState, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Tab {
  key: string;
  label: string;
  content: ReactNode;
}

export function StockTabs({ tabs, defaultKey }: { tabs: Tab[]; defaultKey?: string }) {
  const [active, setActive] = useState(defaultKey ?? tabs[0]?.key);
  const current = tabs.find((t) => t.key === active) ?? tabs[0];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 border-b border-border" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active === t.key}
            data-testid={`tab-${t.key}`}
            onClick={() => setActive(t.key)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              active === t.key
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">{current?.content}</div>
    </div>
  );
}
