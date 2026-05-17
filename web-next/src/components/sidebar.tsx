"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Compass,
  LayoutGrid,
  Menu,
  Moon,
  Search,
  Settings,
  Shield,
  Star,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "거시 (Macro)", icon: Compass },
  { href: "/recommendations", label: "추천 종목", icon: BarChart3 },
  { href: "/themes", label: "테마 (탑다운)", icon: LayoutGrid },
  { href: "/stocks", label: "종목 검색", icon: Search },
  { href: "/watchlist", label: "관심 종목", icon: Star },
  { href: "/closing-trade", label: "종가매매 모드", icon: Moon },
  { href: "/settings", label: "설정", icon: Settings },
];

const ADMIN_NAV = [
  { href: "/admin/access", label: "관리자 — 접근", icon: Shield },
];

function navItems(isAdmin: boolean) {
  return isAdmin ? [...NAV, ...ADMIN_NAV] : NAV;
}

function NavList({
  items,
  pathname,
  onNavigate,
}: {
  items: typeof NAV;
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex flex-col gap-0.5" data-testid="sidebar-nav">
      {items.map((item) => {
        const active =
          pathname === item.href || pathname.startsWith(item.href + "/");
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              // larger touch target on mobile (44px+ recommended), normal on desktop
              "flex items-center gap-2 rounded-md px-3 py-3 md:py-2 text-sm transition-colors",
              active
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="h-4 w-4 shrink-0" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/dashboard" className="px-3 block">
      <div className="text-lg font-semibold tracking-tight">Thesauros</div>
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
        book × ML
      </div>
    </Link>
  );
}

/** Desktop sidebar — visible at md+ only. */
export function Sidebar({ isAdmin = false }: { isAdmin?: boolean }) {
  const pathname = usePathname();
  return (
    <aside className="w-56 border-r border-border bg-background px-3 py-6 hidden md:flex md:flex-col gap-6">
      <Brand />
      <NavList items={navItems(isAdmin)} pathname={pathname} />
    </aside>
  );
}

/**
 * Mobile drawer trigger (hamburger). Renders nothing at md+.
 * Slide-in panel from the left, backdrop, close on link click or backdrop click.
 */
export function MobileNav({ isAdmin = false }: { isAdmin?: boolean }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  // Auto-close drawer whenever we navigate to a new path (browser back/forward).
  // Link clicks are also covered by `onNavigate` below.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(false);
  }, [pathname]);

  // Lock body scroll while drawer is open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="md:hidden rounded-md border border-border p-2 hover:bg-muted"
        aria-label="메뉴 열기"
        aria-expanded={open}
        aria-controls="mobile-nav-drawer"
        data-testid="mobile-nav-toggle"
      >
        <Menu className="h-5 w-5" />
      </button>

      {open && (
        <>
          {/* backdrop */}
          <div
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            onClick={() => setOpen(false)}
            aria-hidden="true"
            data-testid="mobile-nav-backdrop"
          />
          {/* drawer */}
          <aside
            id="mobile-nav-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="메뉴"
            data-testid="mobile-nav-drawer"
            className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-background border-r border-border px-3 py-6 flex flex-col gap-6 md:hidden shadow-xl"
          >
            <div className="flex items-center justify-between">
              <Brand />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md border border-border p-2 hover:bg-muted"
                aria-label="메뉴 닫기"
                data-testid="mobile-nav-close"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <NavList
              items={navItems(isAdmin)}
              pathname={pathname}
              onNavigate={() => setOpen(false)}
            />
          </aside>
        </>
      )}
    </>
  );
}
