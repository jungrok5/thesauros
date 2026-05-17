"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Compass,
  LayoutGrid,
  LineChart,
  Moon,
  Search,
  Settings,
  Shield,
  Star,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "거시 (Macro)", icon: Compass },
  { href: "/recommendations", label: "추천 종목", icon: BarChart3 },
  { href: "/themes", label: "테마 (탑다운)", icon: LayoutGrid },
  { href: "/stocks", label: "종목 검색", icon: Search },
  { href: "/watchlist", label: "관심 종목", icon: Star },
  { href: "/closing-trade", label: "종가매매 모드", icon: Moon },
  { href: "/backtest", label: "백테스트", icon: LineChart },
  { href: "/settings", label: "설정", icon: Settings },
];

const ADMIN_NAV = [
  { href: "/admin/access", label: "관리자 — 접근", icon: Shield },
];

export function Sidebar({ isAdmin = false }: { isAdmin?: boolean }) {
  const pathname = usePathname();
  const items = isAdmin ? [...NAV, ...ADMIN_NAV] : NAV;
  return (
    <aside className="w-56 border-r border-border bg-background px-3 py-6 hidden md:flex md:flex-col gap-1">
      <Link href="/dashboard" className="px-3 mb-6 block">
        <div className="text-lg font-semibold tracking-tight">Thesauros</div>
        <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
          book × ML
        </div>
      </Link>
      <nav className="flex flex-col gap-0.5" data-testid="sidebar-nav">
        {items.map((item) => {
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
