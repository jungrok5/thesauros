"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Compass,
  LineChart,
  Search,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Macro", icon: Compass },
  { href: "/recommendations", label: "Recommendations", icon: BarChart3 },
  { href: "/stocks", label: "Stock Search", icon: Search },
  { href: "/backtest", label: "Backtest", icon: LineChart },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 border-r border-border bg-background px-3 py-6 hidden md:flex md:flex-col gap-1">
      <Link href="/dashboard" className="px-3 mb-6 block">
        <div className="text-lg font-semibold tracking-tight">Thesauros</div>
        <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
          book × ML
        </div>
      </Link>
      <nav className="flex flex-col gap-0.5">
        {NAV.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
