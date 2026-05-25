import Link from "next/link";
import { Bell, Calculator, Shield, ChevronRight, Settings } from "lucide-react";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const session = await auth();
  const u = session?.user as { role?: string } | undefined;
  const isAdmin = u?.role === "admin";

  return (
    <div className="space-y-6 max-w-2xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Settings className="h-6 w-6" /> 설정
        </h1>
      </header>

      <section className="rounded-lg border border-border bg-card p-4">
        <h2 className="text-sm font-medium text-muted-foreground mb-2">계정</h2>
        <dl className="space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">이름</dt>
            <dd>{session?.user?.name ?? "—"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">이메일</dt>
            <dd className="font-mono">{session?.user?.email ?? "—"}</dd>
          </div>
          {isAdmin && (
            <div className="flex justify-between">
              <dt className="text-muted-foreground">권한</dt>
              <dd className="text-blue-700 dark:text-blue-300 font-medium">
                ADMIN
              </dd>
            </div>
          )}
        </dl>
      </section>

      <nav className="space-y-2">
        <Link
          href="/settings/alerts"
          className="flex items-center justify-between rounded-lg border border-border bg-card p-4 hover:bg-muted/30 transition-colors"
        >
          <div className="flex items-start gap-3">
            <Bell className="h-5 w-5 mt-0.5 text-muted-foreground" />
            <div>
              <div className="text-sm font-medium">알림 설정</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                텔레그램 연동 · 웹 푸시 · 알림 종류 (매수/매도/추세 변경 등)
              </div>
            </div>
          </div>
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </Link>

        {/* /tax 는 1년 1번 (12월) 도구라 사이드바 상시 노출 X.
            /guide 의 절세 박스 + 이곳 두 진입점에서 발견 가능 (2026-05-25). */}
        <Link
          href="/tax"
          className="flex items-center justify-between rounded-lg border border-border bg-card p-4 hover:bg-muted/30 transition-colors"
        >
          <div className="flex items-start gap-3">
            <Calculator className="h-5 w-5 mt-0.5 text-muted-foreground" />
            <div>
              <div className="text-sm font-medium">절세 매도 시뮬 (12월)</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                연말 양도세 절감 — 손실 종목 매도/재매수 시뮬레이터
              </div>
            </div>
          </div>
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </Link>

        {isAdmin && (
          <Link
            href="/admin/access"
            className="flex items-center justify-between rounded-lg border border-border bg-card p-4 hover:bg-muted/30 transition-colors"
          >
            <div className="flex items-start gap-3">
              <Shield className="h-5 w-5 mt-0.5 text-muted-foreground" />
              <div>
                <div className="text-sm font-medium">접근 관리 (관리자)</div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  새 사용자 승인/반려
                </div>
              </div>
            </div>
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          </Link>
        )}
      </nav>
    </div>
  );
}
