/**
 * /flow-ranking — 외국인 + 기관 누적 매수 랭킹.
 *
 * 데이터: 기존 `investor_flow` 테이블 (14 일치, 일별 외인/기관/개인
 * 순매수). 새 ingest 불요.
 *
 * 톤: 단순 숫자 표가 아니라 "큰 손이 모이는 곳 / 빠지는 곳" 이 매매에
 * 어떻게 영향 + 후속 액션 안내.
 */
import Link from "next/link";
import { ArrowLeft, TrendingUp, TrendingDown } from "lucide-react";
import { getServerClient } from "@/lib/supabase";
import { fmtKRW } from "@/lib/flow-aggregate";
import { DataFreshness } from "@/components/data-freshness";

/** Latest day for which investor_flow rows exist (daily ingest). */
async function fetchLatestFlowDay(): Promise<string | null> {
  const sb = getServerClient();
  const { data } = await sb
    .from("investor_flow")
    .select("day")
    .order("day", { ascending: false })
    .limit(1)
    .maybeSingle();
  return (data?.day as string | undefined) ?? null;
}

export const dynamic = "force-dynamic";
export const revalidate = 600;  // 10 min — investor_flow updates daily

type Row = {
  ticker: string;
  name: string | null;
  foreign_sum: number;       // 누적 외국인 순매수 (KRW)
  institution_sum: number;   // 누적 기관 순매수
  combined_sum: number;      // foreign + institution
  days: number;              // 데이터 포함 일수 (해당 종목)
};

async function fetchTopRows(direction: "buy" | "sell", limit = 30): Promise<Row[]> {
  const sb = getServerClient();
  // Server-side aggregation via top_flow_rankings RPC (migration 033).
  // 2026-05-20 audit 발견: PostgREST max_rows hard cap = 1000 이라
  // explicit .limit() 명시해도 27K rows 중 첫 1K 만 도착, 랭킹이 부정확.
  // RPC 가 DB-side GROUP BY 로 집계해서 ~30 row 만 wire 전송.
  const { data, error } = await sb.rpc("top_flow_rankings", {
    p_days_back: 14,
    p_limit: limit,
    p_direction: direction,
  });
  if (error || !data) {
    console.error("top_flow_rankings rpc:", error?.message);
    return [];
  }
  type RpcRow = {
    ticker: string;
    foreign_sum: string | number | null;
    institution_sum: string | number | null;
    combined_sum: string | number | null;
    days: number;
  };
  const rpcRows = data as unknown as RpcRow[];
  const top: Row[] = rpcRows.map((r) => ({
    ticker: r.ticker,
    name: null,
    foreign_sum: Number(r.foreign_sum ?? 0),
    institution_sum: Number(r.institution_sum ?? 0),
    combined_sum: Number(r.combined_sum ?? 0),
    days: Number(r.days ?? 0),
  }));
  // Fetch names.
  const tickers = top.map((r) => r.ticker);
  if (tickers.length > 0) {
    const { data: nameRows } = await sb
      .from("tickers")
      .select("ticker, name")
      .in("ticker", tickers);
    const nameMap = new Map(
      ((nameRows ?? []) as unknown as Array<{ ticker: string; name: string | null }>).map(
        (r) => [r.ticker, r.name ?? null],
      ),
    );
    for (const row of top) {
      row.name = nameMap.get(row.ticker) ?? null;
    }
  }
  return top;
}

export default async function FlowRankingPage() {
  const [topBuy, topSell, latestDay] = await Promise.all([
    fetchTopRows("buy", 20),
    fetchTopRows("sell", 20),
    fetchLatestFlowDay(),
  ]);

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <TrendingUp className="h-6 w-6" /> 큰손 매매 랭킹
          </h1>
          <DataFreshness asOf={latestDay} cadence="daily" />
        </div>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          최근 14 일간 <strong>외국인 투자자 + 기관 (자산운용·연기금 등)</strong> 가
          가장 많이 산 종목 (위) / 판 종목 (아래). 큰 손 자금이 어디로
          모이는지 한눈에 — 사이드바 “큰손 매매 랭킹”.
        </p>
      </header>

      {/* 톤 일관 — 사용법 안내 */}
      <section className="rounded-xl border-2 border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-amber-700 dark:text-amber-300">
          💡 이 정보가 매매에 어떤 영향?
        </div>
        <ul className="text-xs space-y-1 leading-relaxed">
          <li className="flex gap-2">
            <span className="text-amber-700 dark:text-amber-300">·</span>
            <span>
              외인 + 기관이 같은 방향이면 신호 강함. 둘이 반대면 의미 약함
              (어느 쪽이 옳을지 분간 어려움).
            </span>
          </li>
          <li className="flex gap-2">
            <span className="text-amber-700 dark:text-amber-300">·</span>
            <span>
              매수 랭킹 상위는 “이미 큰 손 들어간 후 — 추격 vs 동행” 판단 필요.
              차트 정배열 + 매수 신호 동반이면 동행 후보, 단기 급등 후 진입은 회피.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="text-amber-700 dark:text-amber-300">·</span>
            <span>
              매도 랭킹 상위는 보유 중이면 신중 점검. 큰 손 이탈 = 추세 약화 가능성.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="text-amber-700 dark:text-amber-300">·</span>
            <span>
              14 일은 단기. 진짜 추세는 분기 단위 누적이 더 신뢰성 ↑.
              이 페이지는 “요즘 어디로?” 빠른 감 잡기 용도.
            </span>
          </li>
        </ul>
      </section>

      <FlowTable
        title="📈 누적 매수 TOP 20 (14일)"
        rows={topBuy}
        direction="buy"
      />
      <FlowTable
        title="📉 누적 매도 TOP 20 (14일)"
        rows={topSell}
        direction="sell"
      />
    </div>
  );
}

function FlowTable({
  title,
  rows,
  direction,
}: {
  title: string;
  rows: Row[];
  direction: "buy" | "sell";
}) {
  if (rows.length === 0) {
    return (
      <section className="rounded-xl border border-dashed border-border bg-muted/20 p-4 text-sm text-muted-foreground">
        <div className="font-medium mb-1">{title}</div>
        데이터 없음 — investor_flow cron 이 돈 후 다시 확인.
      </section>
    );
  }
  const Icon = direction === "buy" ? TrendingUp : TrendingDown;
  const tone =
    direction === "buy"
      ? "text-rose-600 dark:text-rose-400"
      : "text-sky-600 dark:text-sky-400";
  return (
    <section className="rounded-xl border border-border bg-card overflow-hidden">
      <header className="px-4 py-2.5 border-b border-border bg-muted/30 flex items-center gap-2">
        <Icon className={`h-4 w-4 ${tone}`} />
        <h2 className="text-xs font-semibold tracking-wider uppercase">{title}</h2>
      </header>

      {/* Desktop 표 */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/20">
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">#</th>
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">종목</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">외인</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">기관</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">합계</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={r.ticker}
                className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
              >
                <td className="px-3 py-2 align-top text-muted-foreground">{i + 1}</td>
                <td className="px-3 py-2 align-top">
                  <Link
                    href={`/stocks/${encodeURIComponent(r.ticker)}?from=flow-ranking`}
                    className="block hover:underline"
                  >
                    <div className="font-medium">{r.name ?? r.ticker}</div>
                    <div className="text-[10px] text-muted-foreground font-mono">
                      {r.ticker}
                    </div>
                  </Link>
                </td>
                <td className={`px-3 py-2 text-right font-mono ${r.foreign_sum >= 0 ? "text-rose-600 dark:text-rose-400" : "text-sky-600 dark:text-sky-400"}`}>
                  {fmtKRW(r.foreign_sum)}
                </td>
                <td className={`px-3 py-2 text-right font-mono ${r.institution_sum >= 0 ? "text-rose-600 dark:text-rose-400" : "text-sky-600 dark:text-sky-400"}`}>
                  {fmtKRW(r.institution_sum)}
                </td>
                <td className={`px-3 py-2 text-right font-mono font-medium ${tone}`}>
                  {fmtKRW(r.combined_sum)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile 카드 */}
      <ul className="md:hidden divide-y divide-border">
        {rows.map((r, i) => (
          <li key={r.ticker} className="p-3">
            <Link
              href={`/stocks/${encodeURIComponent(r.ticker)}?from=flow-ranking`}
              className="flex flex-col gap-1"
            >
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <div>
                  <div className="text-xs text-muted-foreground">#{i + 1}</div>
                  <div className="text-sm font-medium">{r.name ?? r.ticker}</div>
                  <div className="text-[10px] font-mono text-muted-foreground">
                    {r.ticker}
                  </div>
                </div>
                <div className={`text-sm font-mono font-medium ${tone}`}>
                  {fmtKRW(r.combined_sum)}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-3 text-[11px]">
                <div className="text-muted-foreground">
                  외인 <span className="font-mono">{fmtKRW(r.foreign_sum)}</span>
                </div>
                <div className="text-muted-foreground">
                  기관 <span className="font-mono">{fmtKRW(r.institution_sum)}</span>
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
