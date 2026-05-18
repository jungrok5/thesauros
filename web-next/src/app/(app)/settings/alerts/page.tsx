/**
 * /settings/alerts — toggle which alert types get sent to Telegram,
 * plus a guide for hooking up the bot the first time.
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { AlertPrefsForm } from "./form-client";
import { TelegramLink } from "./telegram-link-client";
import { PushSubscribe } from "./push-subscribe-client";

export const dynamic = "force-dynamic";

const FIELDS: Array<{ key: string; label: string; help: string }> = [
  { key: "enable_enter",    label: "🟢 매수 진입 신호",
    help: "관심 종목에 강한 매수 / 매수 액션 또는 매수 패턴 (쌍바닥 · 역H&S · 컵핸들 등) 이 발현되면" },
  { key: "enable_pyramid",  label: "🟡 추가 매수 신호 (피라미딩)",
    help: "보유 종목에 추가 매수 패턴 (역H&S · 삼중바닥 · 240MA 돌반지) 이 신선 영역에서 등장하면" },
  { key: "enable_warn",     label: "🟠 경고 신호",
    help: "보유 종목에 매도 반전 패턴 (쌍천장 형성 · 4등분선 50% 깨짐) 이 발현되면" },
  { key: "enable_exit",     label: "🔴 청산 신호 (강력)",
    help: "보유 종목 주봉 10MA 깨짐 · 240MA 이탈 · H&S 완성 — 즉시 청산 권장" },
  { key: "enable_ma240_break",       label: "240MA 돌파/이탈",
    help: "관심/보유 종목의 240MA 라인 통과 시" },
  { key: "enable_quarter_25_break",  label: "4등분선 절대자리 (25%) 깨짐",
    help: "직전 장대양봉 몸통 25% 아래로 종가 — 책 시그니처 매도 시그널" },
  { key: "enable_daily_top5",        label: "⭐ 주간 추천 Top 5",
    help: "매주 금요일 17시 종합 점수 (강도 × 신선도) 상위 5종목 (관심 종목 외 신선 진입 후보)" },
];

async function fetchPrefs(email: string, name: string | null) {
  const userId = await ensureUserId(email, name);
  const sb = getServerClient();
  const { data: prefs } = await sb
    .from("alert_preferences")
    .select("*")
    .eq("user_id", userId)
    .maybeSingle();
  const { data: user } = await sb
    .from("users")
    .select("telegram_chat_id")
    .eq("id", userId)
    .maybeSingle();
  return { prefs, telegramConnected: !!user?.telegram_chat_id };
}

export default async function AlertsSettingsPage() {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");
  const { prefs, telegramConnected } = await fetchPrefs(
    session.user.email.toLowerCase(),
    session.user.name ?? null,
  );

  return (
    <div className="space-y-6 max-w-3xl">
      <Link
        href="/settings"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 설정
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">알림 설정</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          신호가 감지되면 텔레그램으로 즉시 전송됩니다. 매주 금요일 17시 KST 자동 스캔.
        </p>
      </header>

      <TelegramLink connected={telegramConnected} />

      <PushSubscribe />

      <AlertPrefsForm initialPrefs={prefs} fields={FIELDS} />
    </div>
  );
}
