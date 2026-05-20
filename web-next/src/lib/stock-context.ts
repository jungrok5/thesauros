/**
 * Server-side fetch + bundle of the data both <FundamentalVerdicts/>
 * (above-the-fold) and <StockContextTabs/> (deep-dive) need. Single
 * query path so the two consumers don't duplicate Supabase round-trips
 * on the same page render.
 */
import {
  getServerClient,
  type DisclosureRow,
  type FinancialsEvalRow,
  type FactorsEvalRow,
} from "@/lib/supabase";

export type MarketWarningRow = {
  level:
    | "trading_halt"
    | "surveillance"
    | "risk"
    | "warning"
    | "caution"
    | "overheat";
  reason: string | null;
  designated_at: string | null;
  expires_at: string | null;
};

export type ShortSalesRow = {
  day: string;
  short_volume: number | null;
  total_volume: number | null;
  short_ratio: number | null;
  balance_ratio: number | null;
};

export type DividendInfoRow = {
  ex_dividend: string | null;
  record_date: string | null;
  payment_date: string | null;
  dps: number | null;
  yield_pct: number | null;
};

export type AnalystConsensusRow = {
  fiscal_year: number;
  consensus_eps: number | null;
  consensus_revenue: number | null;
  consensus_op_income: number | null;
  target_price: number | null;
};

export type InstitutionalOwnershipRow = {
  holder_name: string;
  holder_type: "NPS" | "AMC" | "FUND" | "AFFILIATE" | "OTHER";
  shares: number | null;
  share_pct: number | null;
  reported_date: string;
};

export type EarningsCalendarRow = {
  expected_date: string;
  report_type: string;
  consensus_eps: number | null;
  actual_eps: number | null;
};

export type StockContext = {
  disclosures: DisclosureRow[];
  fin: FinancialsEvalRow | null;
  fac: FactorsEvalRow | null;
  warnings: MarketWarningRow[];
  shorts: ShortSalesRow[];        // newest-first, ≤ 30 days
  dividend: DividendInfoRow | null;
  consensus: AnalystConsensusRow[];     // forward fiscal years
  holders: InstitutionalOwnershipRow[]; // newest-first ≤ 12 5%-보고 rows
  earnings: EarningsCalendarRow[];      // upcoming ≤ 4
};

export async function fetchStockContext(ticker: string): Promise<StockContext> {
  const sb = getServerClient();
  const todayIso = new Date().toISOString().slice(0, 10);
  const [
    discR, finR, facR, warnR, shortR, divR,
    consR, holdR, earnR,
  ] = await Promise.all([
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
    sb.from("market_warnings")
      .select("level, reason, designated_at, expires_at")
      .eq("ticker", ticker),
    sb.from("short_sales")
      .select("day, short_volume, total_volume, short_ratio, balance_ratio")
      .eq("ticker", ticker)
      .order("day", { ascending: false })
      .limit(30),
    sb.from("dividend_info")
      .select("ex_dividend, record_date, payment_date, dps, yield_pct")
      .eq("ticker", ticker)
      .maybeSingle(),
    sb.from("analyst_consensus")
      .select("fiscal_year, consensus_eps, consensus_revenue, consensus_op_income, target_price")
      .eq("ticker", ticker)
      .order("fiscal_year", { ascending: true })
      .limit(5),
    // Filter by recent reported_date AT THE QUERY so we don't ship the
    // full 5-year history (PK is per-filing; same holder appears
    // dozens of times). 18 months gives "still relevant" without
    // bloating the JSON.
    sb.from("institutional_ownership")
      .select("holder_name, holder_type, shares, share_pct, reported_date")
      .eq("ticker", ticker)
      .gte("reported_date", _dateShift(-540))
      .order("reported_date", { ascending: false })
      .limit(12),
    sb.from("earnings_calendar")
      .select("expected_date, report_type, consensus_eps, actual_eps")
      .eq("ticker", ticker)
      .gte("expected_date", todayIso)
      .order("expected_date", { ascending: true })
      .limit(4),
  ]);
  return {
    disclosures: (discR.data ?? []) as DisclosureRow[],
    fin: finR.data as FinancialsEvalRow | null,
    fac: facR.data as FactorsEvalRow | null,
    warnings: (warnR.data ?? []) as MarketWarningRow[],
    shorts: (shortR.data ?? []) as ShortSalesRow[],
    dividend: divR.data as DividendInfoRow | null,
    consensus: (consR.data ?? []) as AnalystConsensusRow[],
    holders: (holdR.data ?? []) as InstitutionalOwnershipRow[],
    earnings: (earnR.data ?? []) as EarningsCalendarRow[],
  };
}

function _dateShift(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
