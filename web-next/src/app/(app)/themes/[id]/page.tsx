/**
 * /themes/[id] — 테마의 종목 list + 우리 DB 의 종목 정보 (펀더 + action).
 *
 * 추천 X — 사용자가 발견 → 종목 페이지에서 본인 검증.
 */
import Link from "next/link";
import { ArrowLeft, ArrowRight, Hash } from "lucide-react";
import { notFound } from "next/navigation";
import { getServerClient } from "@/lib/supabase";
import { HelpTip } from "@/components/help-tip";
import { DataFreshness } from "@/components/data-freshness";
import { ActionPill } from "@/components/action-pill";
import { RowPrice } from "@/components/row-price";
import { fetchLatestPrices } from "@/lib/latest-prices";
import { SubScoreChips } from "@/components/sub-score-chips";

export const dynamic = "force-dynamic";
export const revalidate = 3600;

interface PageProps {
  params: Promise<{ id: string }>;
}

type ThemeMember = {
  ticker: string;
  name: string | null;
  per: number | null;
  pbr: number | null;
  roe: number | null;
  debt_ratio: number | null;
  op_margin: number | null;
  action: string | null;
  book_score: number | null;
  volume_case_num: number | null;
  quarter_zone: string | null;
  catalyst_bars_since: number | null;
};

function fmtPct(v: number | null, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

async function fetchThemeMembers(themeId: number) {
  const sb = getServerClient();
  // 1) Theme metadata
  const { data: theme } = await sb
    .from("themes")
    .select("theme_id, name, members, updated_at")
    .eq("theme_id", themeId)
    .maybeSingle();
  if (!theme) return null;
  // 2) Theme members + our DB 의 종목 정보 통합 — analyze_results + factors_eval
  const { data: mem } = await sb
    .from("theme_members")
    .select("ticker")
    .eq("theme_id", themeId);
  const tickers = ((mem ?? []) as unknown as { ticker: string }[]).map((r) => r.ticker);
  if (tickers.length === 0) {
    return {
      theme: theme as unknown as { theme_id: number; name: string; members: number; updated_at: string },
      members: [],
      priceMap: new Map(),
    };
  }
  const [{ data: names }, { data: facts }, { data: an }, priceMap] = await Promise.all([
    sb.from("tickers").select("ticker, name").in("ticker", tickers).limit(500),
    sb.from("factors_eval")
      .select("ticker, per, pbr, roe, debt_ratio, op_margin")
      .in("ticker", tickers)
      .limit(500),
    sb.from("analyze_results").select("ticker, result").in("ticker", tickers).limit(500),
    fetchLatestPrices(tickers),
  ]);
  const nameMap = new Map(((names ?? []) as unknown as Array<{ ticker: string; name: string | null }>).map((r) => [r.ticker, r.name]));
  type FacRow = {
    ticker: string;
    per: number | null;
    pbr: number | null;
    roe: number | null;
    debt_ratio: number | null;
    op_margin: number | null;
  };
  const facMap = new Map(((facts ?? []) as unknown as FacRow[]).map((r) => [r.ticker, r]));
  type AnResult = {
    action?: string;
    book_score?: number;
    quarter_zone?: string;
    volume_case?: { case?: number };
    patterns?: Array<{ kind?: string; extra?: { bars_since?: number } }>;
  };
  const anMap = new Map(((an ?? []) as unknown as Array<{ ticker: string; result: AnResult | null }>).map((r) => [r.ticker, r.result]));

  function catalystBarsSince(result: AnResult | null | undefined): number | null {
    if (!result?.patterns) return null;
    let best: number | null = null;
    for (const p of result.patterns) {
      const kind = p?.kind ?? "";
      if (!/catalyst/i.test(kind)) continue;
      const b = p.extra?.bars_since;
      if (typeof b === "number" && (best == null || b < best)) best = b;
    }
    return best;
  }

  const members: ThemeMember[] = tickers.map((t) => {
    const f = facMap.get(t);
    const a = anMap.get(t);
    return {
      ticker: t,
      name: nameMap.get(t) ?? null,
      per: f?.per ?? null,
      pbr: f?.pbr ?? null,
      roe: f?.roe ?? null,
      debt_ratio: f?.debt_ratio ?? null,
      op_margin: f?.op_margin ?? null,
      action: a?.action ?? null,
      book_score: a?.book_score ?? null,
      volume_case_num: a?.volume_case?.case ?? null,
      quarter_zone: a?.quarter_zone ?? null,
      catalyst_bars_since: catalystBarsSince(a),
    };
  });
  // Sort: action priority desc → book_score desc → ROE desc (스크리너와 동일)
  const priority: Record<string, number> = {
    STRONG_BUY: 5, BUY: 4, HOLD: 3, AVOID: 1, SELL: 1, SELL_OR_SHORT: 1,
  };
  members.sort((a, b) => {
    const pa = a.action ? (priority[a.action] ?? 2) : 2;
    const pb = b.action ? (priority[b.action] ?? 2) : 2;
    if (pb !== pa) return pb - pa;
    return (Number(b.book_score) || 0) - (Number(a.book_score) || 0);
  });
  return {
    theme: theme as unknown as { theme_id: number; name: string; members: number; updated_at: string },
    members,
    priceMap,
  };
}

export default async function ThemeDetailPage({ params }: PageProps) {
  const p = await params;
  const themeId = Number(p.id);
  if (!Number.isInteger(themeId) || themeId <= 0) notFound();
  const data = await fetchThemeMembers(themeId);
  if (!data) notFound();
  const { theme, members, priceMap } = data;

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/themes"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 테마 목록으로
      </Link>

      <header>
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Hash className="h-6 w-6" /> {theme.name}
          </h1>
          <DataFreshness asOf={theme.updated_at} cadence="weekly" />
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          총 {members.length} 종목 (Naver Finance 기준). 강매수/매수 우선 정렬.
        </p>
      </header>

      {members.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
          이 테마의 종목 정보 아직 적재 안 됨 — weekly cron 후 표시됩니다.
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          {/* Desktop — same column set as /screener (2026-05-21):
              종목 / PER / PBR / ROE / 부채 / 영업이익률 / 매수 신호 / 상세 */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">종목</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">종가</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                    <HelpTip term="per">PER</HelpTip>
                  </th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                    <HelpTip term="pbr">PBR</HelpTip>
                  </th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                    <HelpTip term="roe">ROE</HelpTip>
                  </th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">부채</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">영업이익률</th>
                  <th className="px-3 py-2 text-center font-medium text-muted-foreground">매수 신호</th>
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">세부</th>
                  <th className="px-3 py-2 text-center font-medium text-muted-foreground"></th>
                </tr>
              </thead>
              <tbody>
                {members.map((m, i) => (
                  <tr
                    key={m.ticker}
                    className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
                  >
                    <td className="px-3 py-2">
                      <Link
                        href={`/stocks/${encodeURIComponent(m.ticker)}?from=themes&theme=${theme.theme_id}`}
                        className="block hover:underline"
                      >
                        <div className="font-medium">{m.name ?? m.ticker}</div>
                        <div className="text-[10px] font-mono text-muted-foreground">{m.ticker}</div>
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      <RowPrice price={priceMap.get(m.ticker) ?? null} ticker={m.ticker} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {m.per != null ? Number(m.per).toFixed(1) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {m.pbr != null ? Number(m.pbr).toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{fmtPct(m.roe)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmtPct(m.debt_ratio, 0)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmtPct(m.op_margin)}</td>
                    <td className="px-3 py-2 text-center">
                      <ActionPill action={m.action} score={m.book_score} />
                    </td>
                    <td className="px-3 py-2">
                      <SubScoreChips
                        volumeCase={m.volume_case_num}
                        quarterZone={m.quarter_zone}
                        catalystBarsSince={m.catalyst_bars_since}
                      />
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Link
                        href={`/stocks/${encodeURIComponent(m.ticker)}?from=themes&theme=${theme.theme_id}`}
                        className="inline-flex items-center gap-0.5 text-xs text-muted-foreground hover:text-foreground"
                      >
                        상세 <ArrowRight className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards — same grid layout as /screener mobile cards. */}
          <ul className="md:hidden divide-y divide-border">
            {members.map((m) => (
              <li key={m.ticker} className="p-3">
                <Link href={`/stocks/${encodeURIComponent(m.ticker)}?from=themes&theme=${theme.theme_id}`} className="flex flex-col gap-2">
                  <div className="flex items-baseline justify-between gap-2 flex-wrap">
                    <div>
                      <div className="text-sm font-medium">{m.name ?? m.ticker}</div>
                      <div className="text-[10px] font-mono text-muted-foreground">{m.ticker}</div>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <RowPrice price={priceMap.get(m.ticker) ?? null} ticker={m.ticker} />
                      <ActionPill action={m.action} score={m.book_score} />
                    </div>
                  </div>
                  <dl className="grid grid-cols-3 gap-x-2 gap-y-1 text-[11px]">
                    <div>
                      <dt className="text-muted-foreground">PER</dt>
                      <dd className="font-mono">{m.per != null ? Number(m.per).toFixed(1) : "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">PBR</dt>
                      <dd className="font-mono">{m.pbr != null ? Number(m.pbr).toFixed(2) : "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">ROE</dt>
                      <dd className="font-mono">{fmtPct(m.roe)}</dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">부채</dt>
                      <dd className="font-mono">{fmtPct(m.debt_ratio, 0)}</dd>
                    </div>
                    <div className="col-span-2">
                      <dt className="text-muted-foreground">영업이익률</dt>
                      <dd className="font-mono">{fmtPct(m.op_margin)}</dd>
                    </div>
                  </dl>
                  <SubScoreChips
                    volumeCase={m.volume_case_num}
                    quarterZone={m.quarter_zone}
                    catalystBarsSince={m.catalyst_bars_since}
                  />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
