/**
 * Themes — Korean theme heatmap (탑다운 3단계).
 *
 * Reads `theme_daily` joined with `themes` for the latest day in the table.
 * Renders a sorted grid sized by membership, colored by 1-day change.
 */
import Link from "next/link";
import { getServerClient } from "@/lib/supabase";

// Theme daily ingest runs once per day; 60s ISR.
export const revalidate = 60;

interface Row {
  theme_id: number;
  name: string;
  members: number;
  change_pct_1d: number | null;
  change_pct_1m: number | null;
  leading_ticker: string | null;
  leading_name: string | null;
  lagging_ticker: string | null;
  lagging_name: string | null;
}

async function fetchThemes() {
  const sb = getServerClient();
  // Newest day available
  const { data: dayRow } = await sb
    .from("theme_daily")
    .select("day")
    .order("day", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (!dayRow?.day) return { day: null, rows: [] as Row[] };
  const day = dayRow.day;

  const { data, error } = await sb
    .from("theme_daily")
    .select("theme_id, change_pct_1d, change_pct_1m, leading_ticker, leading_name, lagging_ticker, lagging_name, themes:theme_id(name, members)")
    .eq("day", day)
    .order("change_pct_1d", { ascending: false, nullsFirst: false });

  if (error) {
    console.error("themes fetch:", error.message);
    return { day, rows: [] };
  }
  const rows: Row[] = (data ?? []).map((r) => {
    const th = (r as { themes?: { name?: string; members?: number } }).themes;
    return {
      theme_id: Number(r.theme_id),
      name: th?.name ?? "—",
      members: Number(th?.members ?? 0),
      change_pct_1d: r.change_pct_1d != null ? Number(r.change_pct_1d) : null,
      change_pct_1m: r.change_pct_1m != null ? Number(r.change_pct_1m) : null,
      leading_ticker: r.leading_ticker as string | null,
      leading_name: r.leading_name as string | null,
      lagging_ticker: r.lagging_ticker as string | null,
      lagging_name: r.lagging_name as string | null,
    };
  });
  return { day, rows };
}

function toneFor(pct: number | null): string {
  if (pct == null) return "bg-card";
  if (pct >= 3) return "bg-rose-600/80 text-white";
  if (pct >= 1) return "bg-rose-500/60 text-white";
  if (pct >= 0.3) return "bg-rose-500/30";
  if (pct > -0.3) return "bg-muted";
  if (pct > -1) return "bg-blue-500/30";
  if (pct > -3) return "bg-blue-500/60 text-white";
  return "bg-blue-600/80 text-white";
}

function sizeFor(members: number): string {
  if (members >= 80) return "col-span-2 row-span-2 text-base";
  if (members >= 40) return "col-span-2 text-sm";
  return "text-xs";
}

export default async function ThemesPage() {
  const { day, rows } = await fetchThemes();

  return (
    <div className="space-y-6 max-w-7xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">테마 (탑다운 3단계)</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          KR 테마 일간 등락률 — 네이버 금융 기준 ·{" "}
          <span className="font-mono">{day ?? "—"}</span>
        </p>
      </header>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
          테마 데이터가 적재되지 않았습니다. 매일 16시 자동 갱신 예정.
        </div>
      ) : (
        <>
          <div className="text-xs text-muted-foreground">
            {rows.length} themes · 🔴 상승 / 🔵 하락 (1일 등락률 기준 정렬)
          </div>

          <div className="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 auto-rows-[100px] gap-2">
            {rows.slice(0, 60).map((r) => (
              <Link
                key={r.theme_id}
                href={`/themes/${r.theme_id}`}
                className={`rounded-lg p-2 border border-border/30 flex flex-col justify-between overflow-hidden hover:opacity-90 transition-opacity ${toneFor(r.change_pct_1d)} ${sizeFor(r.members)}`}
              >
                <div className="font-medium leading-tight truncate" title={r.name}>
                  {r.name}
                </div>
                <div className="flex items-baseline justify-between gap-1 mt-1">
                  <span className="font-mono text-sm font-semibold">
                    {r.change_pct_1d != null
                      ? `${r.change_pct_1d >= 0 ? "+" : ""}${r.change_pct_1d.toFixed(2)}%`
                      : "—"}
                  </span>
                  <span className="opacity-70 text-[10px]">
                    {r.members}종목
                  </span>
                </div>
                {r.leading_ticker && (
                  <div className="text-[10px] opacity-80 truncate mt-0.5" title={r.leading_name ?? ""}>
                    ↑ {r.leading_name}
                  </div>
                )}
              </Link>
            ))}
          </div>

          <details className="rounded-lg border border-border bg-card p-3">
            <summary className="text-sm text-muted-foreground cursor-pointer">
              테이블 보기 (정렬: 1일 등락률 ↓)
            </summary>
            <table className="w-full mt-3 text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="text-left py-1.5 px-2">테마</th>
                  <th className="text-right py-1.5 px-2">1D</th>
                  <th className="text-right py-1.5 px-2">1M</th>
                  <th className="text-right py-1.5 px-2">종목 수</th>
                  <th className="text-left py-1.5 px-2">상위 종목</th>
                  <th className="text-left py-1.5 px-2">하위 종목</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.theme_id} className="border-t border-border/40">
                    <td className="py-1 px-2">{r.name}</td>
                    <td className="text-right font-mono py-1 px-2">
                      {r.change_pct_1d != null ? `${r.change_pct_1d >= 0 ? "+" : ""}${r.change_pct_1d.toFixed(2)}%` : "—"}
                    </td>
                    <td className="text-right font-mono py-1 px-2 text-muted-foreground">
                      {r.change_pct_1m != null ? `${r.change_pct_1m >= 0 ? "+" : ""}${r.change_pct_1m.toFixed(2)}%` : "—"}
                    </td>
                    <td className="text-right py-1 px-2 text-muted-foreground">{r.members}</td>
                    <td className="py-1 px-2 text-xs">
                      {r.leading_ticker ? (
                        <Link href={`/stocks/${encodeURIComponent(r.leading_ticker)}`} className="hover:underline">
                          {r.leading_name}
                        </Link>
                      ) : "—"}
                    </td>
                    <td className="py-1 px-2 text-xs">
                      {r.lagging_ticker ? (
                        <Link href={`/stocks/${encodeURIComponent(r.lagging_ticker)}`} className="hover:underline">
                          {r.lagging_name}
                        </Link>
                      ) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}
