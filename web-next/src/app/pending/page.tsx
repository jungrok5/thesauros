/**
 * /pending — landing page for users whose account is not yet approved.
 * They can submit a one-line reason for the admin to read.
 */
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { signOut } from "@/auth";
import { PendingForm } from "./form-client";

export const dynamic = "force-dynamic";

async function fetchState(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();
  const [{ data: user }, { data: req }] = await Promise.all([
    sb.from("users").select("access_status, role").eq("id", userId).maybeSingle(),
    sb
      .from("access_requests")
      .select("reason, requested_at, decided_at, decision, note")
      .eq("user_id", userId)
      .maybeSingle(),
  ]);
  return {
    status: (user?.access_status ?? "pending") as "pending" | "approved" | "rejected",
    request: req,
  };
}

export default async function PendingPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");

  const { status, request } = await fetchState(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );

  // NB: we deliberately DO NOT `redirect("/dashboard")` when status is
  // approved here, even though it would feel natural. Doing so creates
  // a redirect loop with the proxy when the JWT cookie has a stale
  // "pending" status (the proxy still sends them here, /pending sends
  // them back, ad infinitum → ERR_TOO_MANY_REDIRECTS). Instead we
  // render an "approved!" banner with a manual continue button. The
  // auth.ts JWT callback refreshes the token from DB every 60 s, so
  // a fresh request after that lets the proxy admit the user
  // unconditionally.

  return (
    <div className="min-h-screen flex items-center justify-center bg-background text-foreground p-4">
      <div className="w-full max-w-lg p-8 rounded-2xl border border-border bg-card space-y-5">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Thesauros</h1>
          <p className="text-sm text-muted-foreground">
            로그인됨: <span className="font-mono">{session.user.email}</span>
          </p>
        </header>

        {status === "approved" ? (
          <ApprovedBanner />
        ) : status === "rejected" ? (
          <div
            className="rounded-md border border-rose-500/40 bg-rose-500/5 p-4 text-sm space-y-2"
            data-testid="status-rejected"
          >
            <div className="font-medium text-rose-700 dark:text-rose-300">
              ❌ 사용 요청이 반려되었습니다.
            </div>
            {request?.note && (
              <div className="text-xs text-muted-foreground">
                관리자 메모: {request.note}
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              다시 신청하려면 사유를 적고 제출하세요.
            </p>
          </div>
        ) : request?.requested_at && !request.decided_at ? (
          <div
            className="rounded-md border border-amber-500/40 bg-amber-500/5 p-4 text-sm"
            data-testid="status-pending"
          >
            <div className="font-medium text-amber-700 dark:text-amber-300">
              ⏳ 사용 요청이 접수되었습니다. 관리자 승인을 기다리는 중입니다.
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              요청 시각:{" "}
              {new Date(request.requested_at).toLocaleString("ko-KR")}
            </div>
            {request.reason && (
              <div className="text-xs text-muted-foreground mt-1 italic">
                &quot;{request.reason}&quot;
              </div>
            )}
          </div>
        ) : (
          <div
            className="rounded-md border border-border bg-muted/30 p-4 text-sm text-muted-foreground"
            data-testid="status-new"
          >
            아직 사용 권한이 없습니다. 아래에 간단히 자기소개나 사용 목적을
            적어주시면 관리자가 검토 후 승인합니다.
          </div>
        )}

        {status !== "approved" && (
          <>
            {/* 동의 사항 — 권한 요청 제출 = 아래 두 가지에 동의로 간주.
                별도 체크박스 없이 버튼 클릭 자체가 동의 행동. */}
            <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-4 text-xs space-y-3 leading-relaxed">
              <div className="text-[11px] uppercase tracking-widest text-amber-700 dark:text-amber-300 font-medium">
                📋 사용 요청 전에 — 동의 사항
              </div>
              <div className="space-y-1">
                <div className="font-medium">
                  ⚠️ 매매 결정과 손익은 본인 책임
                </div>
                <p className="text-muted-foreground">
                  사이트의 신호 · 점수 · 액션은 알고리즘 분석 결과 — 미래
                  수익 보장 X. 본인 판단 우선, 손실이 발생해도 운영자에게
                  책임 X.
                </p>
              </div>
              <div className="space-y-1">
                <div className="font-medium">
                  🔧 개발 중 — 데이터 오류 가능
                </div>
                <p className="text-muted-foreground">
                  외부 API (Naver / DART / SEC) + 자체 계산이라 오류·지연
                  가능. 중요 결정 전엔 증권사 앱 / 공식 공시로 재확인.
                </p>
              </div>
              <div className="pt-1 border-t border-amber-500/20 text-amber-700 dark:text-amber-300">
                「사용 요청 보내기」를 누르면 위 두 가지에 동의로 간주됩니다.
              </div>
            </div>
            <PendingForm
              initialReason={request?.reason ?? ""}
              alreadyPending={!!request?.requested_at && !request.decided_at}
            />
          </>
        )}

        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/login" });
          }}
        >
          <button
            type="submit"
            className="w-full text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            로그아웃
          </button>
        </form>
      </div>
    </div>
  );
}

/**
 * Rendered when the DB says "approved". With the per-request JWT
 * refresh for pending users (auth.ts), the proxy itself catches the
 * approved status on the next request — so this banner is mostly a
 * brief in-flight courtesy: the user typically lands here for one
 * page render, clicks the button, and the redirect chain takes them
 * to /dashboard immediately (proxy refreshes JWT → sees approved →
 * redirects /pending → /dashboard on its own from then on).
 */
function ApprovedBanner() {
  return (
    <div
      className="rounded-md border border-emerald-500/40 bg-emerald-500/5 p-4 text-sm space-y-3"
      data-testid="status-approved"
    >
      <div className="font-medium text-emerald-700 dark:text-emerald-300">
        ✅ 사용 요청이 승인되었습니다!
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed">
        아래 버튼을 누르면 대시보드로 이동합니다.
      </p>
      <a
        href="/dashboard"
        className="inline-block w-full text-center rounded-md bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 text-sm font-medium transition-colors"
      >
        대시보드로 이동
      </a>
    </div>
  );
}
