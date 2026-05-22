/**
 * NextDecisionChip — 책 정신을 사용자에게 visualize.
 *
 * 책 2부 3장: "주봉 = 매주 금요일 오후 2시 1회 확인" — 매매 결정은
 * 종가 (15:30 KST) 기준. 페이지 상단에 "다음 결정: D-x" 를 보여줘서
 * 사용자가 매일 들여다보는 충동을 줄이는 게 목적. 책 문구:
 *   • 매매는 안 할수록 좋다
 *   • 와병투자 (한달 누워있다 1회만 확인)
 *   • 코스톨라니: "우량주 샀으면 죄짓고 감옥에 가 있어라"
 *
 * 본 컴포넌트는 server-side 에서 KST 시간만 읽어 D-x 계산 → static.
 * 1분 단위 갱신은 필요 없음 (사용자가 새로고침해도 충분).
 */
import { cn } from "@/lib/utils";

const KST_OFFSET_HOURS = 9;

/** Compute next Friday 15:30 KST as the canonical "다음 결정" anchor.
 *
 *  Why Friday: 책 = 주봉 종가 후 결정. KRX closing auction = 15:20-15:30.
 *  After 15:30 the bar is settled, so the next decision is the *following*
 *  Friday's close.
 *
 *  Why server-side: avoid hydration mismatch — the chip renders the
 *  same string for everyone. Client-side `new Date()` would diverge.
 */
function nextFridayDecisionKst(nowUtc: Date): Date {
  const kst = new Date(nowUtc.getTime() + KST_OFFSET_HOURS * 3600 * 1000);
  // dow: 0 Sun .. 5 Fri .. 6 Sat
  const dow = kst.getUTCDay();   // after offset shift, getUTC* is KST wall-clock
  const hours = kst.getUTCHours();
  const mins = kst.getUTCMinutes();

  let daysAhead: number;
  if (dow === 5) {
    // Friday — if before 15:30 KST, today's close is the upcoming decision.
    // After 15:30, jump to next Friday.
    if (hours < 15 || (hours === 15 && mins < 30)) {
      daysAhead = 0;
    } else {
      daysAhead = 7;
    }
  } else if (dow === 6) {
    daysAhead = 6;   // Saturday → next Friday
  } else {
    // Sunday(0)-Thursday(4)
    daysAhead = 5 - dow;
  }
  const target = new Date(kst);
  target.setUTCDate(target.getUTCDate() + daysAhead);
  target.setUTCHours(15, 30, 0, 0);
  return target;
}

interface Props {
  /** Compact variant — 칩 1 줄. Default fuller card with explainer. */
  compact?: boolean;
  className?: string;
}

export function NextDecisionChip({ compact = false, className }: Props) {
  const nowUtc = new Date();
  const nextDecisionKst = nextFridayDecisionKst(nowUtc);
  const kstNow = new Date(nowUtc.getTime() + KST_OFFSET_HOURS * 3600 * 1000);
  const diffMs = nextDecisionKst.getTime() - kstNow.getTime();
  const diffDays = Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
  const diffHours = Math.max(0, Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60)));

  const dayLabel =
    diffDays === 0
      ? `오늘 ${diffHours}시간 후`
      : diffDays === 1
        ? "내일"
        : `D-${diffDays}`;

  const dateStr = new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit", day: "2-digit", weekday: "short",
    timeZone: "Asia/Seoul",
  }).format(nextDecisionKst);

  if (compact) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border border-amber-500/30 " +
          "bg-amber-500/10 px-2.5 py-1 text-[11px] text-amber-700 dark:text-amber-300 " +
          "font-medium",
          className,
        )}
        title={`다음 매매 결정: ${dateStr} 15:30 KST. 책 정신상 주봉 종가가 매매 결정 기준.`}
      >
        🕒 다음 결정 {dayLabel}
      </span>
    );
  }

  return (
    <section
      className={cn(
        "rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🕒</span>
          <div>
            <div className="text-xs font-medium">다음 매매 결정: {dayLabel}</div>
            <div className="text-[10px] text-muted-foreground">
              {dateStr} 15:30 KST (주봉 종가 기준)
            </div>
          </div>
        </div>
        <div className="text-[10px] text-muted-foreground text-right max-w-[60%] leading-relaxed hidden sm:block">
          책 정신: 매매는 안 할수록 좋다 · 와병투자
        </div>
      </div>
    </section>
  );
}
