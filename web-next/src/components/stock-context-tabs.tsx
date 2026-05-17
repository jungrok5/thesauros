/**
 * Stock context tabs (server component data loader → client tabs widget).
 *
 * Reads from Supabase:
 *  - news (latest 30 by ticker)
 *  - disclosures (latest 30 by ticker)
 *  - financials_eval (3y trend + rule labels)
 *  - factors_eval (4-axis dial + book/academia gates)
 */
import { getServerClient, type NewsRow, type DisclosureRow,
         type FinancialsEvalRow, type FactorsEvalRow } from "@/lib/supabase";
import { StockTabs } from "./stock-tabs";

interface Props {
  ticker: string;
}

async function fetchAll(ticker: string) {
  const sb = getServerClient();
  const [newsR, discR, finR, facR] = await Promise.all([
    sb.from("news")
      .select("id, title, url, source, published_at")
      .eq("ticker", ticker)
      .order("published_at", { ascending: false })
      .limit(30),
    sb.from("disclosures")
      .select("id, rcept_no, report_nm, report_type, filed_date, url")
      .eq("ticker", ticker)
      .order("filed_date", { ascending: false })
      .limit(30),
    sb.from("financials_eval")
      .select("*")
      .eq("ticker", ticker)
      .maybeSingle(),
    sb.from("factors_eval")
      .select("*")
      .eq("ticker", ticker)
      .maybeSingle(),
  ]);

  return {
    news: (newsR.data ?? []) as NewsRow[],
    disclosures: (discR.data ?? []) as DisclosureRow[],
    fin: finR.data as FinancialsEvalRow | null,
    fac: facR.data as FactorsEvalRow | null,
  };
}

/**
 * Small banner that surfaces when the financials/factors row was last
 * re-evaluated. Weekly cron is the producer (weekly-fundamentals.yml);
 * if the row is older than ~14 days it's almost certainly stale.
 *
 * `isStale` is computed by the parent server component (which knows the
 * current request time) so this render stays pure.
 */
function FreshnessNote({
  updatedAt,
  isStale,
}: {
  updatedAt: string | undefined;
  isStale: boolean;
}) {
  if (!updatedAt) return null;
  const cls = isStale
    ? "border-amber-500/40 bg-amber-500/5 text-amber-700 dark:text-amber-300"
    : "border-border bg-muted/30 text-muted-foreground";
  return (
    <div
      className={`rounded-md border px-3 py-1.5 text-xs ${cls}`}
      suppressHydrationWarning
    >
      {isStale ? "⚠️ 데이터가 오래됐습니다 — " : "마지막 갱신: "}
      {new Date(updatedAt).toLocaleString("ko-KR")}
    </div>
  );
}

const STALE_THRESHOLD_DAYS = 14;

function computeStale(updatedAt: string | undefined, nowMs: number): boolean {
  if (!updatedAt) return false;
  const age = (nowMs - new Date(updatedAt).getTime()) /
    (1000 * 60 * 60 * 24);
  return age > STALE_THRESHOLD_DAYS;
}

function NewsTab({ items }: { items: NewsRow[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        뉴스가 아직 적재되지 않았습니다. (한국 종목만 지원, 매일 자동 갱신)
      </div>
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {items.map((n) => (
        <li key={n.id} className="p-3 hover:bg-muted/30 transition-colors">
          <a href={n.url} target="_blank" rel="noopener" className="block group">
            <div className="text-sm group-hover:text-foreground transition-colors">
              {n.title}
            </div>
            <div className="mt-1 text-xs text-muted-foreground flex gap-3">
              <span>{n.source ?? "—"}</span>
              <span>
                {n.published_at
                  ? new Date(n.published_at).toLocaleDateString("ko-KR")
                  : "—"}
              </span>
            </div>
          </a>
        </li>
      ))}
    </ul>
  );
}

function DisclosuresTab({ items }: { items: DisclosureRow[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        공시가 아직 적재되지 않았습니다. (DART, 한국 종목만)
      </div>
    );
  }
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {items.map((d) => (
        <li key={d.id} className="p-3 hover:bg-muted/30 transition-colors">
          <a
            href={d.url ?? "#"}
            target="_blank"
            rel="noopener"
            className="block group"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-xs text-muted-foreground">
                {d.filed_date ?? "—"}
              </span>
              {d.report_type && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                  {d.report_type}
                </span>
              )}
              <span className="text-sm group-hover:text-foreground">
                {d.report_nm}
              </span>
            </div>
          </a>
        </li>
      ))}
    </ul>
  );
}

function fmtKRW(v: number | null | undefined): string {
  if (v == null || !isFinite(v)) return "—";
  if (Math.abs(v) >= 1e12) return `${(v / 1e12).toFixed(2)}조`;
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(1)}억`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(1)}만`;
  return v.toLocaleString("ko-KR");
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function FinancialsTab({ fin, isStale }: { fin: FinancialsEvalRow | null; isStale: boolean }) {
  if (!fin) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        재무 데이터가 적재되지 않았습니다. (DART 한국 종목 우선 지원)
      </div>
    );
  }
  const years = Array.from(
    new Set([
      ...Object.keys(fin.revenue_3y ?? {}),
      ...Object.keys(fin.operating_income_3y ?? {}),
      ...Object.keys(fin.net_income_3y ?? {}),
    ]),
  )
    .map((y) => Number(y))
    .filter((y) => !Number.isNaN(y))
    .sort((a, b) => a - b);

  type Row = { name: string; getter: (y: number) => number | null };
  const rows: Row[] = [
    { name: "매출",       getter: (y) => fin.revenue_3y?.[String(y)] ?? null },
    { name: "영업이익",   getter: (y) => fin.operating_income_3y?.[String(y)] ?? null },
    { name: "순이익",     getter: (y) => fin.net_income_3y?.[String(y)] ?? null },
    { name: "자산",       getter: (y) => fin.assets_3y?.[String(y)] ?? null },
    { name: "부채",       getter: (y) => fin.debt_3y?.[String(y)] ?? null },
    { name: "자기자본",   getter: (y) => fin.equity_3y?.[String(y)] ?? null },
  ];

  const evals = fin.rules_eval ?? {};

  return (
    <div className="space-y-4">
      <FreshnessNote updatedAt={fin.updated_at} isStale={isStale} />
      {fin.summary_text && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm leading-relaxed">
          {fin.summary_text}
        </div>
      )}

      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                항목
              </th>
              {years.map((y) => (
                <th key={y} className="px-3 py-2 text-right font-medium text-muted-foreground">
                  {y}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-t border-border">
                <td className="px-3 py-2">{r.name}</td>
                {years.map((y) => (
                  <td key={y} className="px-3 py-2 text-right font-mono">
                    {fmtKRW(r.getter(y))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <Metric label="ROE" value={fmtPct(fin.roe)} eval={evals.roe} />
        <Metric label="ROA" value={fmtPct(fin.roa)} eval={evals.roa} />
        <Metric label="영업이익률" value={fmtPct(fin.op_margin)} eval={evals.op_margin} />
        <Metric label="부채비율" value={fmtPct(fin.debt_ratio, 0)} eval={evals.debt_ratio} />
        <Metric label="매출 성장 YoY" value={fmtPct(fin.revenue_growth_yoy, 1)} eval={evals.revenue_growth_yoy} />
        <Metric label="순익 성장 YoY" value={fmtPct(fin.net_income_growth_yoy, 1)} />
      </div>
    </div>
  );
}

function Metric({ label, value, eval: evl }: { label: string; value: string; eval?: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-lg font-mono">{value}</div>
      {evl && <div className="mt-1 text-xs">{evl}</div>}
    </div>
  );
}

function FactorsTab({ fac, isStale }: { fac: FactorsEvalRow | null; isStale: boolean }) {
  if (!fac) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
        팩터 평가가 아직 계산되지 않았습니다.
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <FreshnessNote updatedAt={fac.updated_at} isStale={isStale} />
      {fac.summary_text && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm leading-relaxed">
          {fac.summary_text}
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <AxisCard label="가치 (Value)" score={fac.value_score} />
        <AxisCard label="성장 (Growth)" score={fac.growth_score} />
        <AxisCard label="안전 (Safety)" score={fac.safety_score} />
        <AxisCard label="수익 (Quality)" score={fac.quality_score} />
      </div>

      <div className="rounded-lg border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">팩터</th>
              <th className="px-3 py-2 text-right font-medium text-muted-foreground">값</th>
              <th className="px-3 py-2 text-left font-medium text-muted-foreground">평가</th>
            </tr>
          </thead>
          <tbody>
            <FactorRow label="PER" value={fac.per} display={fac.per?.toFixed(1)} evl={fac.per_eval} />
            <FactorRow label="PBR" value={fac.pbr} display={fac.pbr?.toFixed(2)} evl={fac.pbr_eval} />
            <FactorRow label="ROE" value={fac.roe} display={fmtPct(fac.roe)} evl={fac.roe_eval} />
            <FactorRow label="ROA" value={fac.roa} display={fmtPct(fac.roa)} evl={fac.roa_eval} />
            <FactorRow label="영업이익률" value={fac.op_margin} display={fmtPct(fac.op_margin)} evl={fac.op_margin_eval} />
            <FactorRow label="부채비율" value={fac.debt_ratio} display={fmtPct(fac.debt_ratio, 0)} evl={fac.debt_ratio_eval} />
            <FactorRow label="매출 성장" value={fac.revenue_growth} display={fmtPct(fac.revenue_growth, 1)} />
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <div className="text-sm font-medium mb-2">책 + 학계 기준 통과</div>
        <div className="flex flex-wrap gap-2">
          <GateBadge label="강환국 가치 (PBR<1.5 & ROE>10%)" passed={fac.passes_kang_value} />
          <GateBadge label="그레이엄 (PER<15 & 부채<50%)" passed={fac.passes_graham} />
          <GateBadge label="마법공식 (PER<12 & 영업이익률>10%)" passed={fac.passes_magic_formula} />
          <GateBadge label="버핏형 (ROE>15% & 부채<50%)" passed={fac.passes_buffett} />
        </div>
      </div>
    </div>
  );
}

function AxisCard({ label, score }: { label: string; score: number | null }) {
  const s = score ?? 0;
  const tone =
    s >= 8 ? "text-emerald-600 dark:text-emerald-400"
      : s >= 5 ? "text-amber-600 dark:text-amber-400"
        : "text-rose-600 dark:text-rose-400";
  return (
    <div className="rounded-lg border border-border bg-card p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-2xl font-mono ${tone}`}>{s}<span className="text-sm text-muted-foreground">/10</span></div>
    </div>
  );
}

function FactorRow({ label, value, display, evl }: { label: string; value: number | null; display?: string; evl?: string | null }) {
  return (
    <tr className="border-t border-border">
      <td className="px-3 py-2">{label}</td>
      <td className="px-3 py-2 text-right font-mono">{display ?? (value != null ? value.toString() : "—")}</td>
      <td className="px-3 py-2 text-xs">{evl ?? "—"}</td>
    </tr>
  );
}

function GateBadge({ label, passed }: { label: string; passed: boolean | null }) {
  if (passed === true) {
    return <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 px-3 py-1 text-xs">✅ {label}</span>;
  }
  if (passed === false) {
    return <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 text-rose-700 dark:text-rose-300 px-3 py-1 text-xs">❌ {label}</span>;
  }
  return <span className="inline-flex items-center gap-1 rounded-full bg-muted text-muted-foreground px-3 py-1 text-xs">— {label}</span>;
}

export async function StockContextTabs({ ticker }: Props) {
  const { news, disclosures, fin, fac } = await fetchAll(ticker);
  // Server component runs once per request; Date.now() here is the request
  // timestamp, which is the correct reference for staleness vs updated_at.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const finStale = computeStale(fin?.updated_at, now);
  const facStale = computeStale(fac?.updated_at, now);

  return (
    <StockTabs
      defaultKey="news"
      tabs={[
        { key: "news",        label: "뉴스",     content: <NewsTab items={news} /> },
        { key: "disclosures", label: "공시",     content: <DisclosuresTab items={disclosures} /> },
        { key: "financials",  label: "재무제표", content: <FinancialsTab fin={fin} isStale={finStale} /> },
        { key: "factors",     label: "팩터",     content: <FactorsTab fac={fac} isStale={facStale} /> },
      ]}
    />
  );
}
