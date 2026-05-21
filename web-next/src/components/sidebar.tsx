"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BookOpen,
  Compass,
  Filter,
  Hash,
  Map,
  Menu,
  MessageSquare,
  Search,
  Settings,
  Shield,
  Star,
  TrendingUp,
  Volume2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; icon: typeof Compass };
type NavGroup = { heading: string; items: NavItem[] };

/** 그룹별 navigation (2026-05-21):
 *  - 가이드: 처음 시작 + 절세
 *  - 시장 분위기: 거시 (macro)
 *  - 종목 발견: 검색 / 스크리너 / 테마
 *  - 시장 모니터: 큰손 / 거래량
 *  - 내 종목: 관심·보유
 *  - 시스템: 버그·설정
 *
 *  /tax (세금 시뮬레이터) 는 1년에 1번 쓰는 12월 한정 도구라 사이드바
 *  상시 노출 제외. /guide 안의 "12월 절세 매도 시뮬" 박스에서 link 로
 *  발견 가능 (2026-05-20).
 */
const NAV_GROUPS: NavGroup[] = [
  {
    heading: "📖 가이드",
    items: [
      { href: "/welcome", label: "시작하기", icon: BookOpen },
      { href: "/guide", label: "절세·연금", icon: Map },
    ],
  },
  {
    heading: "📍 시장 분위기",
    items: [
      { href: "/dashboard", label: "거시 (Macro)", icon: Compass },
    ],
  },
  {
    heading: "🔎 종목 발견",
    items: [
      { href: "/stocks", label: "종목 검색", icon: Search },
      { href: "/screener", label: "스크리너", icon: Filter },
      { href: "/themes", label: "테마", icon: Hash },
    ],
  },
  {
    heading: "📊 시장 모니터",
    items: [
      { href: "/flow-ranking", label: "큰손 매매 랭킹", icon: TrendingUp },
      { href: "/volume-surge", label: "거래량 폭증", icon: Volume2 },
    ],
  },
  {
    heading: "⭐ 내 종목",
    items: [
      { href: "/watchlist", label: "관심·보유 종목", icon: Star },
    ],
  },
  {
    heading: "⚙️ 시스템",
    items: [
      { href: "/feedback", label: "버그·건의", icon: MessageSquare },
      { href: "/settings", label: "설정", icon: Settings },
    ],
  },
];

const ADMIN_GROUP: NavGroup = {
  heading: "🔒 관리자",
  items: [
    { href: "/admin/access", label: "접근 요청", icon: Shield },
    { href: "/admin/feedback", label: "피드백 관리", icon: MessageSquare },
  ],
};

function navGroups(isAdmin: boolean): NavGroup[] {
  return isAdmin ? [...NAV_GROUPS, ADMIN_GROUP] : NAV_GROUPS;
}

function NavList({
  groups,
  pathname,
  onNavigate,
}: {
  groups: NavGroup[];
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex flex-col gap-3" data-testid="sidebar-nav">
      {groups.map((group) => (
        <div key={group.heading} className="flex flex-col gap-0.5">
          <div className="px-3 text-[10px] uppercase tracking-widest text-muted-foreground/70 font-medium">
            {group.heading}
          </div>
          {group.items.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(item.href + "/");
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                className={cn(
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
        </div>
      ))}
    </nav>
  );
}

function Brand() {
  return (
    <Link href="/dashboard" className="px-3 block">
      <div className="text-lg font-semibold tracking-tight">Thesauros</div>
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
        추세추종 매매 도구
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
      <NavList groups={navGroups(isAdmin)} pathname={pathname} />
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
      {/* Hamburger trigger — positioned to align with the header on the
          left edge. `fixed` + matching `top-2` keeps it visually inside
          the sticky header without being a DOM child of it. */}
      <button
        type="button"
        onClick={() => setOpen(true)}
        // 44px tap target (Apple HIG / Material guidelines): p-2.5 = 10px
        // padding × 2 + 24px icon = 44px. Previous p-2 was 36px.
        className="md:hidden fixed top-2 left-3 z-40 rounded-md border border-border bg-background p-2.5 hover:bg-muted shadow-sm"
        aria-label="메뉴 열기"
        aria-expanded={open}
        aria-controls="mobile-nav-drawer"
        data-testid="mobile-nav-toggle"
      >
        <Menu className="h-6 w-6" />
      </button>

      {open && (
        <>
          {/* backdrop */}
          <div
            className="fixed inset-0 z-50 bg-black/60 md:hidden"
            onClick={() => setOpen(false)}
            aria-hidden="true"
            data-testid="mobile-nav-backdrop"
          />
          {/* drawer — bg-card has a strict CSS token in globals.css; using
              it here (and not bg-background) keeps the drawer fully opaque
              even when a translucent layer is rendered behind it. */}
          <aside
            id="mobile-nav-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="메뉴"
            data-testid="mobile-nav-drawer"
            className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-card text-card-foreground border-r border-border px-3 py-6 flex flex-col gap-6 md:hidden shadow-2xl"
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
              groups={navGroups(isAdmin)}
              pathname={pathname}
              onNavigate={() => setOpen(false)}
            />
          </aside>
        </>
      )}
    </>
  );
}
