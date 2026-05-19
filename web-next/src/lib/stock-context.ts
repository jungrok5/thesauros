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

export type StockContext = {
  disclosures: DisclosureRow[];
  fin: FinancialsEvalRow | null;
  fac: FactorsEvalRow | null;
};

export async function fetchStockContext(ticker: string): Promise<StockContext> {
  const sb = getServerClient();
  const [discR, finR, facR] = await Promise.all([
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
    disclosures: (discR.data ?? []) as DisclosureRow[],
    fin: finR.data as FinancialsEvalRow | null,
    fac: facR.data as FactorsEvalRow | null,
  };
}
