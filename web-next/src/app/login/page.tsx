import { headers } from "next/headers";
import { signIn } from "@/auth";
import { safeCallback } from "@/lib/safe-redirect";
import { Compass, LineChart, Map, AlertTriangle } from "lucide-react";
import { detectInAppBrowser } from "@/lib/in-app-browser";
import { OpenInBrowserHelp } from "./open-in-browser-help";

export const dynamic = "force-dynamic";

interface PageProps {
  searchParams: Promise<{ callbackUrl?: string }>;
}

const FEATURES = [
  {
    icon: Compass,
    title: "거시 환경",
    body: "시장 레짐 · 핵심 지표 · VIX/수익률곡선 한 줄 진단.",
  },
  {
    icon: LineChart,
    title: "종목 분석",
    body: "정배열 · 240MA · 캔들 패턴 자동 스캔 + 신선도 체크.",
  },
  {
    icon: Map,
    title: "절세·연금",
    body: "직접 투자 전 5단계 셋팅으로 매년 +148만원 회수.",
  },
];

export default async function LoginPage({ searchParams }: PageProps) {
  const sp = await searchParams;
  const callbackUrl = safeCallback(sp.callbackUrl);

  // Google OAuth blocks embedded WebViews ("허용되지 않은 사용자
  // 에이전트"). Detect KakaoTalk / Naver / Facebook / Instagram in-app
  // browsers server-side and surface a banner with a "open in browser"
  // helper instead of letting the user hit the dead-end OAuth screen.
  const h = await headers();
  const inApp = detectInAppBrowser(h.get("user-agent"));

  return (
    <div className="relative min-h-screen flex items-center justify-center bg-background text-foreground overflow-hidden">
      {/* Ambient glow — subtle, theme-aware */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 [background:radial-gradient(ellipse_at_top,hsl(var(--accent)/0.35),transparent_60%)]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-emerald-500/10 blur-3xl"
      />

      <div className="relative w-full max-w-md px-4 py-10">
        <div className="rounded-2xl border border-border bg-card/95 backdrop-blur shadow-xl overflow-hidden">
          {/* Brand */}
          <div className="px-7 pt-8 pb-6 border-b border-border">
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
              Thesauros
            </div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">
              추세추종 매매 도구
            </h1>
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
              한국 투자자를 위한 거시 + 종목 + 절세 의사결정 보조.
            </p>
          </div>

          {/* Features */}
          <ul className="px-7 py-5 space-y-3 border-b border-border bg-muted/20">
            {FEATURES.map((f) => {
              const Icon = f.icon;
              return (
                <li key={f.title} className="flex items-start gap-3">
                  <div className="shrink-0 mt-0.5 inline-flex items-center justify-center h-7 w-7 rounded-md border border-border bg-background">
                    <Icon className="h-3.5 w-3.5" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{f.title}</div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      {f.body}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>

          {/* CTA */}
          <div className="px-7 py-6 space-y-4">
            {inApp.isInApp && (
              <div className="rounded-lg border-2 border-amber-500/50 bg-amber-500/10 p-3 space-y-3">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-amber-700 dark:text-amber-300" />
                  <div className="space-y-1">
                    <div className="text-sm font-medium text-amber-900 dark:text-amber-200">
                      {inApp.app === "KakaoTalk"
                        ? "카카오톡 안에서는 Google 로그인이 막혀 있습니다"
                        : `${inApp.app ?? "이 앱"} 안에서는 Google 로그인이 막혀 있습니다`}
                    </div>
                    <p className="text-xs text-amber-800/90 dark:text-amber-200/80 leading-relaxed">
                      Google 보안 정책상 앱 안 브라우저에서는 OAuth 로그인이
                      차단됩니다. 아래 버튼으로 Chrome / Safari 에서 열어주세요.
                    </p>
                  </div>
                </div>
                <OpenInBrowserHelp />
              </div>
            )}
            <form
              action={async () => {
                "use server";
                await signIn("google", { redirectTo: callbackUrl });
              }}
            >
              <button
                type="submit"
                className="group w-full flex items-center justify-center gap-3 px-4 py-3 rounded-lg bg-foreground text-background hover:opacity-90 active:opacity-80 transition text-sm font-medium shadow-sm"
              >
                <svg viewBox="0 0 24 24" className="w-5 h-5">
                  <path
                    fill="#4285F4"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  />
                </svg>
                Google 로 시작하기
              </button>
            </form>

            <p className="text-[11px] text-muted-foreground leading-relaxed">
              누구나 로그인 가능. 처음 로그인하면 사용 요청이 발송되고
              관리자 승인 후 모든 기능을 사용할 수 있습니다.
            </p>
          </div>
        </div>

        <p className="mt-4 text-center text-[10px] text-muted-foreground/70">
          정보 제공 목적 · 투자 결정은 본인 책임
        </p>
      </div>
    </div>
  );
}
