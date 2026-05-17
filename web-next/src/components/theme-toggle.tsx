"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

const NOOP = () => () => {};

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // Hydration guard: false on server / first client paint, true after mount.
  const mounted = useSyncExternalStore(NOOP, () => true, () => false);

  const isDark = mounted && resolvedTheme === "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className="rounded-md border border-border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground flex items-center gap-1.5 transition-colors"
      aria-label="Toggle theme"
      title={mounted ? (isDark ? "라이트 모드로" : "다크 모드로") : "테마"}
    >
      {mounted ? (
        isDark ? (
          <Sun className="h-3.5 w-3.5" />
        ) : (
          <Moon className="h-3.5 w-3.5" />
        )
      ) : (
        <div className="h-3.5 w-3.5" />
      )}
      {mounted ? (isDark ? "Light" : "Dark") : "Theme"}
    </button>
  );
}
