/**
 * Stock detail "시장 신호" section — top-of-page warning banner +
 * companion cards for short sales / dividends. The interpreters
 * (lib/market-signals-interpret.ts) produce structured SignalCard
 * objects with scenarios + actions; this file just renders them.
 *
 * Layout:
 *   - WARNING BANNER: full-width, above-the-fold. Renders only when
 *     warnings exist (skips the "all clear" badge).
 *   - SIGNAL CARDS: row of short-sales + dividend cards. Each may
 *     be null (no data yet) — caller hides those slots.
 */
import { AlertTriangle } from "lucide-react";
import type {
  MarketWarningRow,
  ShortSalesRow,
  DividendInfoRow,
} from "@/lib/stock-context";
import {
  interpretMarketWarnings,
  interpretShortSales,
  interpretDividend,
  type SignalCard as SignalCardData,
  type Tone,
} from "@/lib/market-signals-interpret";

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

// ─────────────────────────────────────────────────────────────────────
// Warning banner — top of page, full width
// ─────────────────────────────────────────────────────────────────────

export function MarketWarningBanner({ warnings }: { warnings: MarketWarningRow[] }) {
  const card = interpretMarketWarnings(warnings);
  if (!card) return null;
  const c = TONE[card.tone];
  return (
    <section
      className={`rounded-xl border-2 ${c.border} ${c.bg} p-4 space-y-3`}
      data-testid="market-warning-banner"
    >
      <header className="flex items-start gap-3">
        <AlertTriangle className={`h-5 w-5 mt-0.5 shrink-0 ${c.text}`} />
        <div className="flex-1 space-y-1">
          <div className={`text-base font-semibold ${c.text}`}>
            {card.label}
          </div>
          <p className="text-sm leading-relaxed">{card.oneLiner}</p>
        </div>
      </header>
      {card.scenarios && card.scenarios.length > 0 && (
        <div className="space-y-2 pl-8">
          {card.scenarios.map((s, i) => (
            <div key={i} className="text-xs leading-relaxed">
              <span className={`font-medium ${c.text}`}>{s.tag}</span>
              <span className="text-muted-foreground"> — {s.body}</span>
            </div>
          ))}
        </div>
      )}
      <div className="pl-8 space-y-1">
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

// ─────────────────────────────────────────────────────────────────────
// Short sales + dividend card row
// ─────────────────────────────────────────────────────────────────────

export function ShortAndDividendCards({
  shorts,
  dividend,
  todayIso,
}: {
  shorts: ShortSalesRow[];
  dividend: DividendInfoRow | null;
  todayIso: string;
}) {
  const shortSummary = summarizeShorts(shorts);
  const shortCard = interpretShortSales(shortSummary);
  const divCard = dividend
    ? interpretDividend({
        exDividend: dividend.ex_dividend,
        recordDate: dividend.record_date,
        paymentDate: dividend.payment_date,
        dps: dividend.dps,
        yieldPct: dividend.yield_pct,
        todayIso,
      })
    : null;

  // 공매도는 KRX 클라우드 IP 차단으로 영구히 수집 불가능 (pykrx 폐기,
  // 2026-05-20). 데이터 있는 종목만 카드 렌더 — Empty placeholder 는
  // "곧 채워질 것" 오해를 만들어서 제거. 배당은 Naver finance.annual
  // 로 정상 수집 — 데이터 없으면 (DPS=0) Empty 카드 유지.
  if (!shortCard && !divCard) return null;

  // 둘 다 데이터 없으면 위에서 이미 null. 하나라도 있으면 그 카드만
  // 단독 렌더 (Empty placeholder 안 띄움).
  return (
    <section className={
      shortCard && divCard
        ? "grid grid-cols-1 md:grid-cols-2 gap-3"
        : "block"
    }>
      {shortCard && <SignalCard card={shortCard} title="공매도" />}
      {!shortCard && divCard && null /* 공매도 placeholder 안 띄움 */}
      {divCard ? <SignalCard card={divCard} title="배당" /> : null}
    </section>
  );
}

function SignalCard({ card, title }: { card: SignalCardData; title: string }) {
  const c = TONE[card.tone];
  return (
    <article className={`rounded-xl border-2 ${c.border} ${c.bg} p-4 space-y-3`}>
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-semibold tracking-tight">{title}</h3>
        <span
          className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${c.border} ${c.text} bg-background/40`}
        >
          {card.label}
        </span>
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
    </article>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function summarizeShorts(rows: ShortSalesRow[]) {
  const latest = rows[0];
  const last5 = rows.slice(0, 5).map((r) => r.short_ratio).filter(
    (x): x is number => x != null,
  );
  return {
    latestDay: latest?.day ?? null,
    balanceRatio: latest?.balance_ratio ?? null,
    todayRatio: latest?.short_ratio ?? null,
    fiveDayAvgRatio:
      last5.length > 0 ? last5.reduce((a, b) => a + b, 0) / last5.length : null,
  };
}
