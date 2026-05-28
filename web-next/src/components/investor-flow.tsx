/**
 * Investor flow strip on stock detail.
 *
 * 2026-05-28 — pulls 14 trading days (was 5) and renders a cumulative
 * line chart (외국인 / 기관 / 개인 누적 순매수) above the 5-row
 * numeric table. The chart shows trend at a glance; the table keeps
 * day-by-day exact numbers visible.
 *
 * Source: Naver Finance `frgn.naver` page (not KIS — the comment used
 * to say KIS but ingest_investor_flow.py crawls Naver). Detailed
 * investor types (연기금 / 투신 / 사모 / etc) are NOT available
 * per-ticker from any cloud-reachable source — see
 * project_security_followups for the reconnaissance trail.
 */
import { getServerClient } from "@/lib/supabase";
import { InvestorFlowChart } from "@/components/investor-flow-chart";

interface Row {
  day: string;
  foreign_net: number | null;
  institution_net: number | null;
  individual_net: number | null;
}

async function fetchFlow(ticker: string, days = 14): Promise<Row[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("investor_flow")
    .select("day, foreign_net, institution_net, individual_net")
    .eq("ticker", ticker)
    .order("day", { ascending: false })
    .limit(days);
  if (error) {
    console.error("investor_flow fetch:", error.message);
    return [];
  }
  return (data ?? []).map((r) => ({
    day: String(r.day),
    foreign_net: r.foreign_net != null ? Number(r.foreign_net) : null,
    institution_net: r.institution_net != null ? Number(r.institution_net) : null,
    individual_net: r.individual_net != null ? Number(r.individual_net) : null,
  }));
}

function fmt(n: number | null): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(1)}억`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(1)}만`;
  return `${sign}${abs}`;
}

function tone(n: number | null): string {
  if (n == null) return "text-muted-foreground";
  return n > 0 ? "text-rose-500" : n < 0 ? "text-blue-500" : "text-muted-foreground";
}

interface Props {
  ticker: string;
}

export async function InvestorFlow({ ticker }: Props) {
  const isKR = /\.(KS|KQ)$/.test(ticker);
  if (!isKR) return null;
  const rows = await fetchFlow(ticker);
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground">
        외국인/기관 매매 동향 데이터 없음 (Naver Finance 자동 갱신, 매일 17시 KST)
      </div>
    );
  }

  // Compute 5-day net flow per role
  const sumF = rows.reduce((a, r) => a + (r.foreign_net ?? 0), 0);
  const sumI = rows.reduce((a, r) => a + (r.institution_net ?? 0), 0);

  // Show the 5 most-recent rows in the numeric table (rows arrives DESC).
  const tableRows = rows.slice(0, 5);

  return (
    <div className="rounded-lg border border-border bg-card p-3 space-y-3">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="text-xs text-muted-foreground">
          외국인/기관 매매 동향 (최근 {rows.length}일, Naver Finance)
        </div>
        <div className="text-xs">
          외 <span className={tone(sumF)}>{fmt(sumF)}</span>
          {" / "}
          기 <span className={tone(sumI)}>{fmt(sumI)}</span>
          <span className="text-muted-foreground"> (5일 합계 KRW)</span>
        </div>
      </div>
      <InvestorFlowChart rows={rows} />
      <table className="w-full text-xs">
        <thead className="text-muted-foreground">
          <tr>
            <th className="text-left py-1">날짜</th>
            <th className="text-right py-1">외국인</th>
            <th className="text-right py-1">기관</th>
            <th className="text-right py-1">개인</th>
          </tr>
        </thead>
        <tbody>
          {tableRows.map((r) => (
            <tr key={r.day} className="border-t border-border/40">
              <td className="py-1">{r.day}</td>
              <td className={`text-right font-mono py-1 ${tone(r.foreign_net)}`}>{fmt(r.foreign_net)}</td>
              <td className={`text-right font-mono py-1 ${tone(r.institution_net)}`}>{fmt(r.institution_net)}</td>
              <td className={`text-right font-mono py-1 ${tone(r.individual_net)}`}>{fmt(r.individual_net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
