/**
 * ActionPill — book-action label + book_score in one chip.
 *
 * Used by stock-list tables (/screener and /themes/[id]) so a row's
 * BUY/STRONG_BUY/HOLD/AVOID verdict + 10-point book score read as a
 * single visual unit. Extracted from /screener (2026-05-21) so the two
 * pages don't drift apart.
 *
 *   <ActionPill action="STRONG_BUY" score={0.95} />  → 🟢 강매수 · 9.5/10
 *   <ActionPill action={null} score={null} />        → 대기
 */

const LABEL: Record<string, string> = {
  STRONG_BUY: "🟢 강매수",
  BUY: "🟡 매수",
  HOLD: "⚪ 보류",
  AVOID: "🔴 회피",
  SELL: "🔴 청산",
  SELL_OR_SHORT: "🔴 매도/숏",
};

export function ActionPill({
  action,
  score,
}: {
  action: string | null;
  score: number | null;
}) {
  if (!action) {
    return (
      <span className="inline-flex items-center rounded-full bg-muted text-muted-foreground px-2 py-0.5 text-[10px]">
        대기
      </span>
    );
  }
  const isAvoid =
    action === "AVOID" || action === "SELL" || action === "SELL_OR_SHORT";
  const tone =
    action === "STRONG_BUY"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
      : action === "BUY"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
        : isAvoid
          ? "bg-rose-500/15 text-rose-700 dark:text-rose-300"
          : "bg-muted text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] ${tone}`}
    >
      {LABEL[action] ?? action}
      {score != null && ` · ${(score * 10).toFixed(1)}/10`}
    </span>
  );
}
