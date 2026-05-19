/**
 * Above-the-fold strip of "한 줄 평" cards for the stock detail page:
 *
 *   ┌─────────────────────────┬─────────────────────────┐
 *   │ 재무 건전성             │ 가치투자 통과 (팩터)    │
 *   │ 🟢 우수 / 🟡 양호 …    │ 🟢 우수 / 🟡 양호 …    │
 *   │ one-liner               │ one-liner               │
 *   │ · takeaway              │ · takeaway              │
 *   │ · takeaway              │ · takeaway              │
 *   └─────────────────────────┴─────────────────────────┘
 *
 * Previously buried inside the 종목 정보 → 재무제표 / 팩터 tabs at the
 * very bottom of the page. Surfaced up top so the user gets the
 * fundamental judgment alongside the trend-following verdict without
 * scrolling + tab-clicking. The tabs still own the deep-dive (3y
 * table, factor grid, gate badges).
 */
import {
  interpretFinancials,
  interpretFactors,
  type Interpretation,
} from "@/lib/fundamentals-interpret";
import type {
  FinancialsEvalRow,
  FactorsEvalRow,
} from "@/lib/supabase";

interface Props {
  fin: FinancialsEvalRow | null;
  fac: FactorsEvalRow | null;
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

export function FundamentalVerdicts({ fin, fac }: Props) {
  // Page renders nothing if neither table has a row yet — keeps the
  // detail page tidy for freshly-added tickers that haven't been
  // evaluated by the weekly cron.
  if (!fin && !fac) return null;

  return (
    <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {fin ? (
        <VerdictCard
          label="재무 건전성"
          subLabel="DART / SEC 재무 → 성장 · 수익 · 안전 가중 평가"
          interp={interpretFinancials(fin)}
          deepLink="📋 재무제표 탭에서 3년 추이 + 룰별 평가"
        />
      ) : (
        <Empty label="재무 건전성" />
      )}
      {fac ? (
        <VerdictCard
          label="가치투자 통과"
          subLabel="PER · PBR · 4축 + 4대 스크리닝 (강환국 · 그레이엄 · 마법공식 · 버핏)"
          interp={interpretFactors(fac)}
          deepLink="🎯 팩터 탭에서 4축 점수 + 게이트 통과 여부"
        />
      ) : (
        <Empty label="가치투자 통과" />
      )}
    </section>
  );
}

function VerdictCard({
  label,
  subLabel,
  interp,
  deepLink,
}: {
  label: string;
  subLabel: string;
  interp: Interpretation;
  deepLink: string;
}) {
  const c = TONE[interp.tone];
  return (
    <article className={`rounded-xl border-2 ${c.border} ${c.bg} p-4 space-y-3`}>
      <header className="space-y-1">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h3 className="text-sm font-semibold tracking-tight">{label}</h3>
          <span
            className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${c.border} ${c.text} bg-background/40`}
          >
            {interp.label}
          </span>
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

function Empty({ label }: { label: string }) {
  return (
    <article className="rounded-xl border border-dashed border-border bg-muted/20 p-4 text-xs text-muted-foreground">
      <div className="font-medium text-foreground/80 mb-1">{label}</div>
      데이터 미적재 — 주간 cron 후 자동 채워짐.
    </article>
  );
}
