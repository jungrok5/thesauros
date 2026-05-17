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

  // If this page is reached but status is already approved, bounce home.
  if (status === "approved") redirect("/dashboard");

  return (
    <div className="min-h-screen flex items-center justify-center bg-background text-foreground p-4">
      <div className="w-full max-w-lg p-8 rounded-2xl border border-border bg-card space-y-5">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Thesauros</h1>
          <p className="text-sm text-muted-foreground">
            로그인됨: <span className="font-mono">{session.user.email}</span>
          </p>
        </header>

        {status === "rejected" ? (
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

        <PendingForm
          initialReason={request?.reason ?? ""}
          alreadyPending={!!request?.requested_at && !request.decided_at}
        />

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
