/**
 * Server wrapper: fetches market-wide investor trend rows for KOSPI +
 * KOSDAQ from `market_investor_trend`, hands them to the client chart
 * for the interactive label-focus UX.
 *
 * Data: 3-axis (개인 / 외국인 / 기관계), KRW 백만, signed.
 * Source: ingest_market_investor_trend cron (m.stock Naver API).
 *
 * Why only 3 axes (not the 7-type 금융투자/투신/사모/etc breakdown):
 * 5-axis reconnaissance (2026-05-28) confirmed no public Naver HTTP
 * endpoint serves the 7-type market-wide history. The retail page
 * (sise/investorDealTrendDay.naver) returns empty body for all
 * bizdates. See migrations/058 header comment.
 */
import { getServerClient } from "@/lib/supabase";
import { MarketInvestorTrendChart, type MarketRow } from "@/components/market-investor-trend-chart";

const DAYS = 30;

async function fetchTrend(market: "KOSPI" | "KOSDAQ"): Promise<MarketRow[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("market_investor_trend")
    .select("day, individual_net, foreign_net, institution_net")
    .eq("market", market)
    .order("day", { ascending: false })
    .limit(DAYS);
  if (error) {
    console.error("market_investor_trend fetch:", error.message);
    return [];
  }
  return (data ?? []).map((r) => ({
    day: String(r.day),
    individual_net: r.individual_net != null ? Number(r.individual_net) : null,
    foreign_net: r.foreign_net != null ? Number(r.foreign_net) : null,
    institution_net: r.institution_net != null ? Number(r.institution_net) : null,
  }));
}

export async function MarketInvestorTrend() {
  const [kospi, kosdaq] = await Promise.all([
    fetchTrend("KOSPI"),
    fetchTrend("KOSDAQ"),
  ]);
  if (kospi.length === 0 && kosdaq.length === 0) {
    return null;
  }
  return <MarketInvestorTrendChart kospi={kospi} kosdaq={kosdaq} />;
}
