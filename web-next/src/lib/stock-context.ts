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

export type StockContext = {
  disclosures: DisclosureRow[];
  fin: FinancialsEvalRow | null;
  fac: FactorsEvalRow | null;
  warnings: MarketWarningRow[];
  shorts: ShortSalesRow[];        // newest-first, ≤ 30 days
  dividend: DividendInfoRow | null;
};

export async function fetchStockContext(ticker: string): Promise<StockContext> {
  const sb = getServerClient();
  const [discR, finR, facR, warnR, shortR, divR] = await Promise.all([
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
  ]);
  return {
    disclosures: (discR.data ?? []) as DisclosureRow[],
    fin: finR.data as FinancialsEvalRow | null,
    fac: facR.data as FactorsEvalRow | null,
    warnings: (warnR.data ?? []) as MarketWarningRow[],
    shorts: (shortR.data ?? []) as ShortSalesRow[],
    dividend: divR.data as DividendInfoRow | null,
  };
}
