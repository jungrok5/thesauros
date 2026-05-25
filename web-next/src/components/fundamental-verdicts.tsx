/**
 * Above-the-fold "재무 건전성" card on the stock detail page.
 *
 *   ┌────────────────────────────────────────────────────┐
 *   │ 재무 건전성                                        │
 *   │ 🟢 우수 / 🟡 양호 / 🟠 부진 / 🔴 적자              │
 *   │ one-liner                                          │
 *   │ · takeaway                                         │
 *   │ · takeaway                                         │
 *   └────────────────────────────────────────────────────┘
 *
 * 2026-05-26 site-direction reset: dropped the second "가치투자 통과
 * (팩터)" card. The screener already removed the value-investing
 * presets (그레이엄/버핏/마법공식/딥밸류) for book-spirit consistency —
 * exposing a "가치투자 통과" verdict on stock detail was the same
 * value-investing frame in a different surface, and the user flagged
 * it during the alignment review. The raw factor data is still
 * available in the 종목 정보 → 팩터 탭 for those who want to dig.
 */
import {
  interpretFinancials,
  type Interpretation,
} from "@/lib/fundamentals-interpret";
import type {
  FinancialsEvalRow,
} from "@/lib/supabase";
import { DataFreshness } from "@/components/data-freshness";

interface Props {
  fin: FinancialsEvalRow | null;
}

const TONE: Record<
  Interpretation["tone"],
  { border: string; bg: string; text: string }
> = {
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

export function FundamentalVerdicts({ fin }: Props) {
  // Page renders nothing if the financials_eval row is missing —
  // keeps the detail page tidy for freshly-added tickers that
  // haven't been evaluated by the weekly cron yet.
  if (!fin) return null;

  return (
    <section className="max-w-2xl">
      <VerdictCard
        label="재무 건전성"
        subLabel="DART / SEC 재무 → 성장 · 수익 · 안전 가중 평가"
        interp={interpretFinancials(fin)}
        deepLink="📋 재무제표 탭에서 3년 추이 + 룰별 평가"
        asOf={fin.updated_at}
      />
    </section>
  );
}

function VerdictCard({
  label,
  subLabel,
  interp,
  deepLink,
  asOf,
}: {
  label: string;
  subLabel: string;
  interp: Interpretation;
  deepLink: string;
  /** financials_eval/factors_eval row 의 updated_at — quarterly cron. */
  asOf?: string | null;
}) {
  const c = TONE[interp.tone];
  return (
    <article className={`rounded-xl border-2 ${c.border} ${c.bg} p-4 space-y-3`}>
      <header className="space-y-1">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h3 className="text-sm font-semibold tracking-tight">{label}</h3>
          <div className="flex items-center gap-2 flex-wrap">
            <DataFreshness asOf={asOf ?? null} cadence="quarterly" />
            <span
              className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${c.border} ${c.text} bg-background/40`}
            >
              {interp.label}
            </span>
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {subLabel}
        </p>
      </header>

      <p className="text-sm leading-relaxed">{interp.oneLiner}</p>

      {interp.takeaways.length > 0 && (
        <ul className="space-y-1 text-xs leading-relaxed">
          {interp.takeaways.map((t, i) => (
            <li key={i} className="flex gap-2">
              <span className={c.text}>·</span>
              <span>{t}</span>
            </li>
          ))}
        </ul>
      )}

      <p className="text-[10px] text-muted-foreground/70 italic">
        ↓ {deepLink}
      </p>
    </article>
  );
}

