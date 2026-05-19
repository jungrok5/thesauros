/**
 * Company overview card — shows business summary + industry + most-recent
 * filings on /stocks/[ticker]. Reads from the company_profile table
 * (populated weekly by app.data.ingest_company_profile).
 *
 * Phase 3 of the search-only pivot: replaces the universe-wide auto-
 * classification with focused per-ticker context so the user can answer
 * "what does this company actually do?" without leaving the page.
 */
import { getServerClient } from "@/lib/supabase";

interface Filing {
  type?: string;
  date?: string;
  title?: string;
  url?: string;
}

interface Profile {
  source: string;
  industry: string | null;
  sectors: string[] | null;
  summary: string | null;
  ceo: string | null;
  founded: string | null;
  hq: string | null;
  website: string | null;
  last_filings: Filing[] | null;
  updated_at: string;
}

async function loadProfile(ticker: string): Promise<Profile | null> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("company_profile")
    .select(
      "source, industry, sectors, summary, ceo, founded, hq, website, last_filings, updated_at",
    )
    .eq("ticker", ticker)
    .maybeSingle();
  if (error) {
    console.error("company_profile read:", error.message);
    return null;
  }
  return (data as unknown as Profile) ?? null;
}

interface Props {
  ticker: string;
}

export async function CompanyProfile({ ticker }: Props) {
  const p = await loadProfile(ticker);
  if (!p || !p.summary) {
    // Soft-fail — pages without company profile data still render.
    return null;
  }
  const filings = (p.last_filings ?? []).slice(0, 5);
  return (
    <section className="rounded-lg border border-border bg-card p-4 space-y-3">
      <header className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="text-sm font-semibold tracking-wide uppercase text-muted-foreground">
          회사 개요
        </h2>
        <span className="text-[10px] text-muted-foreground">
          출처 {p.source}
        </span>
      </header>
      <p className="text-sm leading-relaxed">{p.summary}</p>
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {p.industry && (
          <div>
            <dt className="opacity-60">산업</dt>
            <dd className="text-foreground">{p.industry}</dd>
          </div>
        )}
        {p.ceo && (
          <div>
            <dt className="opacity-60">대표</dt>
            <dd className="text-foreground">{p.ceo}</dd>
          </div>
        )}
        {p.founded && (
          <div>
            <dt className="opacity-60">설립</dt>
            <dd className="text-foreground">{p.founded}</dd>
          </div>
        )}
        {p.hq && (
          <div>
            <dt className="opacity-60">본사</dt>
            <dd className="text-foreground">{p.hq}</dd>
          </div>
        )}
        {p.website && (
          <div className="col-span-2 md:col-span-4">
            <dt className="opacity-60">웹사이트</dt>
            <dd>
              <a
                href={p.website}
                target="_blank"
                rel="noopener noreferrer"
                className="text-foreground underline hover:no-underline"
              >
                {p.website}
              </a>
            </dd>
          </div>
        )}
      </dl>

      {filings.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            최근 공시 {filings.length}건
          </summary>
          <ul className="mt-2 space-y-1">
            {filings.map((f, i) => (
              <li key={i} className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] opacity-60 shrink-0">
                  {f.date ?? ""}
                </span>
                <span className="text-[10px] rounded border border-border px-1.5 opacity-70 shrink-0">
                  {f.type ?? ""}
                </span>
                {f.url ? (
                  <a
                    href={f.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline"
                  >
                    {f.title ?? ""}
                  </a>
                ) : (
                  <span>{f.title ?? ""}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
