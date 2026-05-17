/**
 * 5-axis macro dial from Supabase macro_state singleton.
 *
 * Renders: 5 axis scores (liquidity / rate / cycle / price / fear) + MV=PQ
 * signal + one-line guidance. Updated by `python -m app.db.publish_macro`.
 */
import { getServerClient, type MacroStateRow } from "@/lib/supabase";
import { HelpTip } from "@/components/help-tip";

const AXIS_LABELS: Record<string, { label: string; term: string }> = {
  liquidity: { label: "통화·유동성", term: "macro_liquidity" },
  rate:      { label: "금리",       term: "macro_rate" },
  cycle:     { label: "경기",       term: "macro_cycle" },
  price:     { label: "물가",       term: "macro_price" },
  fear:      { label: "시장 심리",   term: "macro_fear" },
};

function dotColor(score: number): string {
  if (score >= 4) return "bg-emerald-500";
  if (score >= 3) return "bg-amber-500";
  if (score >= 2) return "bg-orange-500";
  return "bg-rose-500";
}

export async function MacroDial() {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("macro_state")
    .select("global_status, kr_status, indices, mv_pq_signal, dial_scores, one_line_guidance, updated_at")
    .eq("id", 1)
    .maybeSingle();

  if (error || !data) return null;
  const row = data as MacroStateRow;
  const dial = row.dial_scores;
  const total = dial
    ? Object.values(dial).reduce((a, b) => a + b, 0)
    : null;
  const updated = new Date(row.updated_at).toLocaleString("ko-KR");

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-baseline justify-between gap-3 mb-4 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-widest text-muted-foreground">
            거시 환경 한눈에 (5축 다이얼)
          </div>
          <div className="mt-1 text-sm font-medium">
            {row.one_line_guidance ?? "—"}
          </div>
        </div>
        <div className="text-xs text-muted-foreground font-mono">
          종합 {total ?? "?"}/25 · 갱신 {updated}
        </div>
      </div>

      {dial && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
          {Object.entries(AXIS_LABELS).map(([k, meta]) => {
            const score = (dial as Record<string, number>)[k] ?? 0;
            return (
              <div key={k} className="text-center">
                <div className="text-xs text-muted-foreground mb-2 inline-flex items-center justify-center">
                  <HelpTip term={meta.term}>{meta.label}</HelpTip>
                </div>
                <div className="flex justify-center gap-1">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <span
                      key={i}
                      className={`inline-block w-3 h-3 rounded-full ${
                        i <= score ? dotColor(score) : "bg-muted/30"
                      }`}
                      aria-label={i <= score ? "filled" : "empty"}
                    />
                  ))}
                </div>
                <div className="mt-1 text-xs font-mono">{score}/5</div>
              </div>
            );
          })}
        </div>
      )}

      {row.mv_pq_signal && (
        <div className="text-xs text-muted-foreground border-t border-border/60 pt-3">
          <span className="font-medium">
            <HelpTip term="mv_pq">MV=PQ 시그널</HelpTip>:
          </span>{" "}
          {row.mv_pq_signal}
        </div>
      )}
    </section>
  );
}
