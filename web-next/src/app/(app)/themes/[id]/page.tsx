/**
 * /themes/[id] — 테마의 종목 list + 우리 DB 의 종목 정보 (펀더 + action).
 *
 * 추천 X — 사용자가 발견 → 종목 페이지에서 본인 검증.
 */
import Link from "next/link";
import { ArrowLeft, Hash } from "lucide-react";
import { notFound } from "next/navigation";
import { getServerClient } from "@/lib/supabase";
import { HelpTip } from "@/components/help-tip";
import { DataFreshness } from "@/components/data-freshness";

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
  action: string | null;
  book_score: number | null;
};

const ACTION_LABEL: Record<string, { label: string; cls: string }> = {
  STRONG_BUY:    { label: "🟢 강매수", cls: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300" },
  BUY:           { label: "🟡 매수",   cls: "bg-amber-500/15 text-amber-700 dark:text-amber-300" },
  HOLD:          { label: "⚪ 보류",   cls: "bg-zinc-500/15 text-zinc-700 dark:text-zinc-300" },
  AVOID:         { label: "🔴 회피",   cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
  SELL:          { label: "🔴 청산",   cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
  SELL_OR_SHORT: { label: "🔴 매도/숏", cls: "bg-rose-500/15 text-rose-700 dark:text-rose-300" },
};

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
    return { theme: theme as unknown as { theme_id: number; name: string; members: number; updated_at: string }, members: [] };
  }
  const [{ data: names }, { data: facts }, { data: an }] = await Promise.all([
    sb.from("tickers").select("ticker, name").in("ticker", tickers).limit(500),
    sb.from("factors_eval").select("ticker, per, pbr, roe").in("ticker", tickers).limit(500),
    sb.from("analyze_results").select("ticker, result").in("ticker", tickers).limit(500),
  ]);
  const nameMap = new Map(((names ?? []) as unknown as Array<{ ticker: string; name: string | null }>).map((r) => [r.ticker, r.name]));
  const facMap = new Map(((facts ?? []) as unknown as Array<{ ticker: string; per: number | null; pbr: number | null; roe: number | null }>).map((r) => [r.ticker, r]));
  const anMap = new Map(((an ?? []) as unknown as Array<{ ticker: string; result: { action?: string; book_score?: number } | null }>).map((r) => [r.ticker, r.result]));
  const members: ThemeMember[] = tickers.map((t) => {
    const f = facMap.get(t);
    const a = anMap.get(t);
    return {
      ticker: t,
      name: nameMap.get(t) ?? null,
      per: f?.per ?? null,
      pbr: f?.pbr ?? null,
      roe: f?.roe ?? null,
      action: a?.action ?? null,
      book_score: a?.book_score ?? null,
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
  };
}

export default async function ThemeDetailPage({ params }: PageProps) {
  const p = await params;
  const themeId = Number(p.id);
  if (!Number.isInteger(themeId) || themeId <= 0) notFound();
  const data = await fetchThemeMembers(themeId);
  if (!data) notFound();
  const { theme, members } = data;

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
          {/* Desktop */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/30">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">종목</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                    <HelpTip term="per">PER</HelpTip>
                  </th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                    <HelpTip term="pbr">PBR</HelpTip>
                  </th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                    <HelpTip term="roe">ROE</HelpTip>
                  </th>
                  <th className="px-3 py-2 text-center font-medium text-muted-foreground">차트 신호</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">책 점수 (/10)</th>
                </tr>
              </thead>
              <tbody>
                {members.map((m, i) => {
                  const actionInfo = m.action ? ACTION_LABEL[m.action] : null;
                  return (
                    <tr
                      key={m.ticker}
                      className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
                    >
                      <td className="px-3 py-2">
                        <Link
                          href={`/stocks/${encodeURIComponent(m.ticker)}`}
                          className="block hover:underline"
                        >
                          <div className="font-medium">{m.name ?? m.ticker}</div>
                          <div className="text-[10px] font-mono text-muted-foreground">{m.ticker}</div>
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.per != null ? Number(m.per).toFixed(1) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.pbr != null ? Number(m.pbr).toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.roe != null ? `${(Number(m.roe) * 100).toFixed(1)}%` : "—"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        {actionInfo ? (
                          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] ${actionInfo.cls}`}>
                            {actionInfo.label}
                          </span>
                        ) : (
                          <span className="text-[10px] text-muted-foreground">분석 대기</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {m.book_score != null
                          ? `${(Number(m.book_score) * 10).toFixed(1)}/10`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* Mobile cards */}
          <ul className="md:hidden divide-y divide-border">
            {members.map((m) => {
              const actionInfo = m.action ? ACTION_LABEL[m.action] : null;
              return (
                <li key={m.ticker} className="p-3">
                  <Link href={`/stocks/${encodeURIComponent(m.ticker)}`} className="block space-y-1">
                    <div className="flex items-baseline justify-between gap-2 flex-wrap">
                      <span className="text-sm font-medium">{m.name ?? m.ticker}</span>
                      {actionInfo && (
                        <span className={`text-[10px] rounded-full px-2 py-0.5 ${actionInfo.cls}`}>
                          {actionInfo.label}
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-mono text-muted-foreground">{m.ticker}</div>
                    <div className="text-[11px] text-muted-foreground">
                      PER {m.per != null ? Number(m.per).toFixed(1) : "—"} ·
                      PBR {m.pbr != null ? Number(m.pbr).toFixed(2) : "—"} ·
                      ROE {m.roe != null ? `${(Number(m.roe) * 100).toFixed(1)}%` : "—"} ·
                      책점수 {m.book_score != null ? `${(Number(m.book_score) * 10).toFixed(1)}/10` : "—"}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
