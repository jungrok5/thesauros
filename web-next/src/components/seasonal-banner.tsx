/**
 * Dashboard top-of-page seasonal banner — Halloween indicator + nearby
 * Korean-market calendar events (배당 시즌, 정기주총, MSCI 리밸런싱).
 *
 * Renders the same `SignalCard` shape as the per-stock cards: tone +
 * one-liner + scenarios + actions. Tone is "good" in the bullish window
 * (Nov-Apr) and "neutral" in the bearish window (May-Oct); we don't
 * use "warn"/"bad" here because the seasonal effect is a statistical
 * tilt, not a hard rule.
 */
import { interpretSeasonal, type Tone } from "@/lib/market-signals-interpret";

const TONE: Record<Tone, { border: string; bg: string; text: string }> = {
  good: {
    border: "border-emerald-500/40",
    bg: "bg-emerald-500/5",
    text: "text-emerald-700 dark:text-emerald-300",
  },
  neutral: {
    border: "border-amber-500/40",
    bg: "bg-amber-500/5",
    text: "text-amber-700 dark:text-amber-300",
  },
  warn: {
    border: "border-orange-500/40",
    bg: "bg-orange-500/5",
    text: "text-orange-700 dark:text-orange-300",
  },
  bad: {
    border: "border-rose-500/40",
    bg: "bg-rose-500/5",
    text: "text-rose-700 dark:text-rose-300",
  },
};

export function SeasonalBanner({ todayIso }: { todayIso: string }) {
  const card = interpretSeasonal({ todayIso });
  const c = TONE[card.tone];
  return (
    <section className={`rounded-xl border-2 ${c.border} ${c.bg} p-4 space-y-3`}>
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
            🗓️ 시즌 + 캘린더
          </div>
          <h2 className={`text-base font-semibold tracking-tight ${c.text}`}>
            {card.label}
          </h2>
        </div>
      </header>
      <p className="text-sm leading-relaxed">{card.oneLiner}</p>
      {card.scenarios && card.scenarios.length > 0 && (
        <div className="space-y-2">
          {card.scenarios.map((s, i) => (
            <div key={i} className="text-xs leading-relaxed">
              <span className={`font-medium ${c.text}`}>{s.tag}</span>
              <span className="text-muted-foreground"> — {s.body}</span>
            </div>
          ))}
        </div>
      )}
      <div className="space-y-1">
        <div className={`text-[10px] uppercase tracking-widest ${c.text}`}>
          액션
        </div>
        <ul className="text-xs space-y-1 leading-relaxed">
          {card.actions.map((a, i) => (
            <li key={i} className="flex gap-2">
              <span className={c.text}>·</span>
              <span>{a}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
