/**
 * /volume-surge — 거래량 폭증 종목 모니터 (주봉 기준).
 *
 * 일봉 데이터는 우리가 안 가지고 있어서 (DB 500 MB 한도) \"오늘 폭증\"
 * 은 못 잡지만, 주봉 기준 \"이번 주 거래량 vs 직전 평균\" 으로 추세
 * 전환 / 큰 손 진입 신호는 충분히 잡힘. 책 정신 §거래량 12 케이스에
 * 따라 \"거래량 + 가격 + 위치\" 조합이 매수/매도 결정의 핵심.
 *
 * 데이터: 기존 bars (granularity='W') — 추가 cron 불요.
 */
import Link from "next/link";
import { ArrowLeft, Volume2 } from "lucide-react";
import { getServerClient } from "@/lib/supabase";
import {
  interpretSurge,
  fmtVol,
  type SurgeHit,
} from "@/lib/volume-surge";

export const dynamic = "force-dynamic";
export const revalidate = 600;

type Hit = SurgeHit & { name: string | null };

async function fetchSurges(): Promise<Hit[]> {
  const sb = getServerClient();
  // Server-side aggregation via volume_surges RPC (migration 033).
  // 2026-05-20 audit: PostgREST max_rows hard cap = 1000 이라 9주 × ~2900
  // tickers = 26K rows 중 첫 1K 만 도착하던 문제 fix. RPC 는 DB-side
  // window function 으로 ticker 별 this/avg 계산 후 ~30 row 만 전송.
  const { data, error } = await sb.rpc("volume_surges", {
    p_min_ratio: 2.0,
    p_min_samples: 4,
    p_limit: 30,
  });
  if (error || !data) {
    console.error("volume_surges rpc:", error?.message);
    return [];
  }
  type RpcRow = {
    ticker: string;
    this_week_vol: string | number | null;
    avg_vol: string | number | null;
    ratio: string | number | null;
    this_week_close: string | number | null;
    prev_week_close: string | number | null;
    price_change_pct: string | number | null;
  };
  const rpcRows = data as unknown as RpcRow[];
  const top: Hit[] = rpcRows.map((r) => ({
    ticker: r.ticker,
    name: null,
    thisWeekVol: Number(r.this_week_vol ?? 0),
    avgVol: Number(r.avg_vol ?? 0),
    ratio: Number(r.ratio ?? 0),
    thisWeekClose: Number(r.this_week_close ?? 0),
    prevWeekClose: Number(r.prev_week_close ?? 0),
    priceChangePct: Number(r.price_change_pct ?? 0),
  }));
  // Names.
  if (top.length > 0) {
    const { data: namesRaw } = await sb
      .from("tickers")
      .select("ticker, name")
      .in("ticker", top.map((h) => h.ticker));
    const nameRows = (namesRaw ?? []) as unknown as Array<{
      ticker: string;
      name: string | null;
    }>;
    const nameMap = new Map(nameRows.map((r) => [r.ticker, r.name ?? null]));
    for (const h of top) h.name = nameMap.get(h.ticker) ?? null;
  }
  return top;
}

export default async function VolumeSurgePage() {
  const hits = await fetchSurges();

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Volume2 className="h-6 w-6" /> 거래량 폭증 모니터
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          이번 주 거래량이 직전 8 주 평균의 <strong>2 배 이상</strong> 인 종목.
          큰 손이 들어오거나 빠지는 중 — 추세 전환 신호.
        </p>
      </header>

      <section className="rounded-xl border-2 border-sky-500/40 bg-sky-500/5 p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-sky-700 dark:text-sky-300">
          💡 거래량 폭증이 의미하는 것
        </div>
        <ul className="text-xs space-y-1 leading-relaxed">
          <li className="flex gap-2">
            <span className="text-sky-700 dark:text-sky-300">·</span>
            <span>
              <strong>가격 ↑ + 거래량 폭증</strong> = 큰 손 매집. 매수 후보 (단, 추격 매수 X).
            </span>
          </li>
          <li className="flex gap-2">
            <span className="text-sky-700 dark:text-sky-300">·</span>
            <span>
              <strong>가격 ↓ + 거래량 폭증</strong> = 큰 손 이탈. 보유자는 즉시 점검.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="text-sky-700 dark:text-sky-300">·</span>
            <span>
              <strong>가격 정체 + 거래량 폭증</strong> = 방향 미정 “폭풍 전 고요”. 다음 주 가격으로 판단.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="text-sky-700 dark:text-sky-300">·</span>
            <span>
              주봉 기준 — 일봉 “오늘” 폭증은 종목 상세의 LastClose + 차트로 확인.
            </span>
          </li>
        </ul>
      </section>

      {hits.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
          폭증 종목 없음 (이번 주 / 평균의 2 배 이상). 시장이 조용한 시기.
        </div>
      ) : (
        <section className="rounded-xl border border-border bg-card overflow-hidden">
          <header className="px-4 py-2.5 border-b border-border bg-muted/30">
            <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
              📊 거래량 폭증 종목 (이번 주, 2× 이상)
            </h2>
          </header>

          {/* Desktop */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/20">
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">종목</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">이번주 거래량</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">평균 (8주)</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">배수</th>
                  <th className="px-3 py-2 text-right font-medium text-muted-foreground">주가 변동</th>
                  <th className="px-3 py-2 text-left font-medium text-muted-foreground">신호 + 액션</th>
                </tr>
              </thead>
              <tbody>
                {hits.map((h, i) => {
                  const interp = interpretSurge(h);
                  return (
                    <tr
                      key={h.ticker}
                      className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
                    >
                      <td className="px-3 py-2 align-top">
                        <Link
                          href={`/stocks/${encodeURIComponent(h.ticker)}`}
                          className="block hover:underline"
                        >
                          <div className="font-medium">{h.name ?? h.ticker}</div>
                          <div className="text-[10px] text-muted-foreground font-mono">
                            {h.ticker}
                          </div>
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {fmtVol(h.thisWeekVol)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                        {fmtVol(h.avgVol)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-medium">
                        {h.ratio.toFixed(1)}×
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-mono ${
                          h.priceChangePct >= 0
                            ? "text-rose-600 dark:text-rose-400"
                            : "text-sky-600 dark:text-sky-400"
                        }`}
                      >
                        {h.priceChangePct >= 0 ? "+" : ""}
                        {h.priceChangePct.toFixed(1)}%
                      </td>
                      <td className="px-3 py-2">
                        <div className={`text-xs font-medium ${interp.tone}`}>
                          {interp.label}
                        </div>
                        <div className="text-[10px] text-muted-foreground mt-0.5 leading-relaxed">
                          {interp.action}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile */}
          <ul className="md:hidden divide-y divide-border">
            {hits.map((h) => {
              const interp = interpretSurge(h);
              return (
                <li key={h.ticker} className="p-3 space-y-2">
                  <Link
                    href={`/stocks/${encodeURIComponent(h.ticker)}`}
                    className="flex items-baseline justify-between gap-2 flex-wrap"
                  >
                    <div>
                      <div className="text-sm font-medium">{h.name ?? h.ticker}</div>
                      <div className="text-[10px] text-muted-foreground font-mono">
                        {h.ticker}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-mono font-medium">
                        {h.ratio.toFixed(1)}×
                      </div>
                      <div
                        className={`text-xs font-mono ${
                          h.priceChangePct >= 0
                            ? "text-rose-600 dark:text-rose-400"
                            : "text-sky-600 dark:text-sky-400"
                        }`}
                      >
                        {h.priceChangePct >= 0 ? "+" : ""}
                        {h.priceChangePct.toFixed(1)}%
                      </div>
                    </div>
                  </Link>
                  <div className="text-[10px] text-muted-foreground">
                    이번 주 {fmtVol(h.thisWeekVol)} · 평균 {fmtVol(h.avgVol)}
                  </div>
                  <div className="rounded-md border border-border bg-muted/30 p-2">
                    <div className={`text-xs font-medium ${interp.tone}`}>
                      {interp.label}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-0.5 leading-relaxed">
                      {interp.action}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
