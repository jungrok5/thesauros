/**
 * BookEntrySpots — dashboard preview of the screener's TOP 3.
 *
 * 2026-05-26 alignment fix: previously this card pulled raw scan_results
 * ordered by strength DESC, while /screener used the screener_results
 * RPC ordered by book_score DESC. The two surfaces showed different
 * tickers for the same nominal concept ("이번 주 책 진입 자리"). A real
 * dashboard dump vs /screener dump showed 0% top-3 overlap — one of the
 * dashboard's TOP 3 wasn't in /screener at all (펀더 미통과).
 *
 * Fix: call the same screener_results RPC the /screener page uses, take
 * the first 3 rows. Dashboard preview ≡ first 3 of the screener list,
 * 1:1. The 더보기 link lands the user on the same dataset, just longer.
 *
 * SL column was source-of-truth — kept, but driven by `volume_case_num`
 * which the RPC already returns. The rule is identical to the previous
 * signal-based logic: volume_case_3 (바닥 폭증) and action='STRONG_BUY'
 * are the only two cases SL=10% has historically helped on (per the
 * sweep_per_signal_sl backtest).
 */
import Link from "next/link";
import { getServerClient } from "@/lib/supabase";
import { PRESETS } from "@/lib/screener-presets";

// Dashboard card = preview only (TOP 3) — full list lives in /screener.
const DEFAULT_LIMIT = 3;

type Spot = {
  ticker: string;
  name: string | null;
  action: string | null;        // STRONG_BUY / BUY / ... — RPC column
  book_score: number | null;
  roe: number | null;
  volume_case_num: number | null;
  catalyst_bars_since: number | null;
};

async function fetchTopSpots(limit: number): Promise<Spot[]> {
  const sb = getServerClient();
  // Same RPC + same filter as /screener page (book-buy preset).
  const preset = PRESETS[0];
  const f = preset.filter;
  const { data, error } = await sb.rpc("screener_results", {
    p_per_min: null,
    p_per_max: null,
    p_pbr_max: null,
    p_roe_min: f.roeMin ?? null,
    p_debt_ratio_max: null,
    p_op_margin_min: null,
    p_revenue_growth_min: null,
    p_passes_graham: null,
    p_passes_buffett: null,
    p_passes_magic: null,
    p_passes_kang: null,
    p_action: null,
    p_action_in: f.actionIn ?? null,
    p_book_score_min: f.bookScoreMin ?? null,
    p_limit: limit,
    p_quarter_zone: null,
    p_volume_surge: null,
    p_catalyst_max_weeks: null,
  });
  if (error || !data) {
    console.error("BookEntrySpots fetch:", error?.message);
    return [];
  }
  type RpcRow = {
    ticker: string;
    name: string | null;
    action: string | null;
    book_score: string | number | null;
    roe: string | number | null;
    volume_case_num: number | null;
    catalyst_bars_since: number | null;
  };
  return (data as unknown as RpcRow[]).slice(0, limit).map((r) => ({
    ticker: r.ticker,
    name: r.name,
    action: r.action,
    book_score: r.book_score == null ? null : Number(r.book_score),
    roe: r.roe == null ? null : Number(r.roe),
    volume_case_num: r.volume_case_num,
    catalyst_bars_since: r.catalyst_bars_since,
  }));
}

function actionLabel(action: string | null): string {
  if (action === "STRONG_BUY") return "🟢 강한 매수";
  if (action === "BUY") return "🟡 매수";
  if (action === "HOLD") return "⚪ 보류";
  return "—";
}

function slPolicy(action: string | null, volCase: number | null): {
  badge: string; cls: string;
} {
  // sweep_per_signal_sl backtest: SL=10% historically helps only on
  // volume_case_3 (바닥 폭증) and action=STRONG_BUY. Other signals do
  // worse with SL on. Mirror the same policy as the Telegram SL alert.
  const slOn = action === "STRONG_BUY" || volCase === 3;
  return slOn
    ? { badge: "10%", cls: "text-emerald-700 dark:text-emerald-300 bg-emerald-500/10" }
    : { badge: "OFF",  cls: "text-zinc-700 dark:text-zinc-300 bg-zinc-500/10" };
}

export async function BookEntrySpots({ limit = DEFAULT_LIMIT }: { limit?: number } = {}) {
  const spots = await fetchTopSpots(limit);

  if (spots.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="text-sm text-muted-foreground">
          현재 책 정신 매수 후보 (펀더 + 분석 통과) 종목이 없습니다.
          다음 주봉 마감 후 자동 갱신됩니다.
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-4 space-y-3">
      <header className="flex items-baseline justify-between flex-wrap gap-2">
        <h2 className="text-base font-semibold tracking-tight">
          📍 책 정신 매수 후보 — TOP {limit}
        </h2>
        <span className="text-xs text-muted-foreground">
          스크리너 정렬 동일 — book_score 내림차순
        </span>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs uppercase text-muted-foreground border-b border-border">
            <tr>
              <th className="text-left py-1.5 pr-2">순위</th>
              <th className="text-left py-1.5 px-2">종목</th>
              <th className="text-left py-1.5 px-2">신호</th>
              <th className="text-right py-1.5 px-2">점수</th>
              <th className="text-right py-1.5 px-2">ROE</th>
              <th className="text-right py-1.5 px-2">SL</th>
            </tr>
          </thead>
          <tbody>
            {spots.map((s, i) => {
              const sl = slPolicy(s.action, s.volume_case_num);
              return (
                <tr key={s.ticker} className="border-b border-border/40 last:border-0">
                  <td className="py-2 pr-2 text-muted-foreground">{i + 1}</td>
                  <td className="px-2">
                    <Link
                      href={`/stocks/${encodeURIComponent(s.ticker)}?from=dashboard`}
                      className="hover:underline"
                    >
                      <span className="font-mono text-xs">{s.ticker}</span>
                      {s.name && (
                        <span className="ml-1.5 font-medium">{s.name}</span>
                      )}
                    </Link>
                  </td>
                  <td className="px-2">{actionLabel(s.action)}</td>
                  <td className="text-right px-2 font-semibold">
                    {s.book_score == null ? "—" : s.book_score.toFixed(2)}
                  </td>
                  <td className="text-right px-2">
                    {s.roe == null ? "—" : `${(s.roe * 100).toFixed(1)}%`}
                  </td>
                  <td className="text-right px-2">
                    <span className={`${sl.cls} px-1.5 py-0.5 rounded text-xs`}>
                      {sl.badge}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap pt-1 border-t border-emerald-500/20">
        <p className="text-xs text-muted-foreground leading-relaxed">
          TOP {limit} 미리보기 — 더 많은 후보는 스크리너에서. SL 컬럼 = 신호별
          stop-loss 추천 (volume_case_3 + STRONG_BUY 만 ON 권장).
        </p>
        <Link
          href="/screener"
          className="text-xs font-medium text-emerald-700 dark:text-emerald-300 hover:underline whitespace-nowrap"
        >
          스크리너에서 전체 보기 →
        </Link>
      </div>
    </section>
  );
}
