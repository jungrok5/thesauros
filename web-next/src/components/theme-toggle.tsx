"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

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
