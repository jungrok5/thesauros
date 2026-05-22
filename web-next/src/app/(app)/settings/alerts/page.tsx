/**
 * /settings/alerts — toggle which alert types get sent to Telegram,
 * plus a guide for hooking up the bot the first time.
 */
import Link from "next/link";
import { ArrowLeft, Bell } from "lucide-react";
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { ensureUserId, getServerClient } from "@/lib/supabase";
import { AlertPrefsForm } from "./form-client";
import { TelegramLink } from "./telegram-link-client";
import { PushSubscribe } from "./push-subscribe-client";

export const dynamic = "force-dynamic";

// Three categories grouped by the 책-spirit principle:
//   - DECISION  : 책 결정 단위. 주봉 종가 후만 발사 (현재는 daily-scan
//                 의 한 부분 — P1 에서 weekly-scan 으로 분리될 예정).
//   - EVENT     : 매일 발생하는 선행 신호 (공시 / 외인+기관 / 거래량).
//                 책 정신상 매매 결정 ≠ 정보 — 별 카테고리.
//   - PRICE     : 사용자가 미리 지정한 자동 청산 트리거. 장중 OK.
//
// 와병투자 모드 (bedrest_mode) 는 별도 — ON 이면 위 3 카테고리 모두
// 무시하고 주 1회 통합 요약만. 책 2부 3장의 "한달 누워있다 1회만 확인"
// 정신.
const CATEGORIES: Array<{
  title: string;
  intro: string;
  fields: Array<{ key: string; label: string; help: string }>;
}> = [
  {
    title: "🟢 결정 알림",
    intro:
      "주봉 마감 (금요일 종가) 후 발사. 책 정신: 매매 결정은 종가 기준.",
    fields: [
      { key: "enable_enter", label: "매수 진입 신호",
        help: "관심 종목에 강한 매수 / 매수 액션 또는 매수 패턴 (쌍바닥 · 역H&S · 컵핸들 등) 이 발현되면" },
      { key: "enable_pyramid", label: "추가 매수 신호 (피라미딩)",
        help: "보유 종목에 추가 매수 패턴 (역H&S · 삼중바닥 · 240MA 돌반지) 이 신선 영역에서 등장하면" },
      { key: "enable_warn", label: "🟠 경고 신호",
        help: "보유 종목에 매도 반전 패턴 (쌍천장 형성 · 4등분선 50% 깨짐) 이 발현되면" },
      { key: "enable_exit", label: "🔴 청산 신호 (강력)",
        help: "보유 종목 주봉 10MA 깨짐 · 240MA 이탈 · H&S 완성 — 즉시 청산 권장" },
      { key: "enable_ma240_break", label: "240MA 돌파/이탈",
        help: "관심/보유 종목의 240MA 라인 통과 시" },
      { key: "enable_quarter_25_break", label: "4등분선 절대자리 (25%) 깨짐",
        help: "직전 장대양봉 몸통 25% 아래로 종가 — 책 시그니처 매도 시그널" },
    ],
  },
  {
    title: "🟡 이벤트 알림",
    intro:
      "매일 발생하는 선행 신호. 책 정신: 거래량 / 외인+기관 동행 = 선행성, " +
      "공시 = 사건성 정보. 매매 결정은 본인 차트 검증 후.",
    fields: [
      { key: "enable_disclosure", label: "📢 새 공시 알림 (DART)",
        help: "관심/보유 종목에 새 DART 공시가 올라오면 즉시 알림 — 자사주 매입 / 유상증자 / 5% 지분 변동 / 실적 발표 등. 매일 17 시 KST 스캔" },
    ],
  },
  // PRICE 카테고리는 watchlist 종목의 target/stop hit. 토글이 아니라
  // watchlist 행마다 사용자 지정 → 별도 settings 안 필요. UI 안내만.
];

// Flat field list — telegram_worker 와 DB schema 가 알아야 하는 키
// 전체. 카테고리 그룹화는 표시 전용. 새 필드 추가 시 두 곳에 같이 추가.
const ALL_FIELDS = CATEGORIES.flatMap((c) => c.fields);

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
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Bell className="h-6 w-6" /> 알림 설정
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          신호가 감지되면 텔레그램으로 즉시 전송됩니다. 매주 금요일 17시 KST 자동 스캔.
        </p>
      </header>

      <TelegramLink connected={telegramConnected} />

      <PushSubscribe />

      <AlertPrefsForm
        initialPrefs={prefs}
        categories={CATEGORIES}
        allFields={ALL_FIELDS}
      />
    </div>
  );
}
