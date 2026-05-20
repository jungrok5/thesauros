/**
 * 투자자 인텔리전스 카드 묶음 — 컨센서스 / 큰손 지분 / 실적 발표.
 *
 * 모두 server-rendered (props 만 받음). 각 카드는 데이터가 없으면
 * 자체적으로 렌더 안 함 — null 반환. /stocks/[ticker] 에서 하나만
 * 박아두면 데이터 있는 종목만 자동으로 보임.
 *
 * 톤: 데이터 → 시나리오 → 액션. "무슨 의미야 / 뭘 하란 거야" 가
 * 카드만 봐도 답이 나오도록.
 */
import type {
  AnalystConsensusRow,
  InstitutionalOwnershipRow,
  EarningsCalendarRow,
} from "@/lib/stock-context";
import {
  consensusActionLine,
  holdersActionLine,
  earningsActionLine,
  daysFromToday,
} from "@/lib/investor-intel-actions";

const NUMBER_FMT = new Intl.NumberFormat("ko-KR");
const PCT_FMT = new Intl.NumberFormat("ko-KR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function fmtKrw(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return NUMBER_FMT.format(Math.round(n));
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${PCT_FMT.format(n)}%`;
}

// 액수 큰 매출/영업이익은 억 단위로 떨어뜨려야 사람이 읽을 수 있음.
// Naver finance.annual 값은 100만 원 (백만) 단위로 옴 → 100 으로 나누면 억.
function fmtEokFromMillion(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const eok = Math.round(n / 100);
  return `${NUMBER_FMT.format(eok)}억`;
}

// ─────────────────────────────────────────────────────────────────────
// 1. 컨센서스 + 목표주가
// ─────────────────────────────────────────────────────────────────────

export function ConsensusCard({
  consensus,
  lastClose,
}: {
  consensus: AnalystConsensusRow[];
  lastClose?: number | null;
}) {
  if (!consensus || consensus.length === 0) return null;

  // 가장 가까운 forward year (어차피 ingest 가 미래만 씀).
  const primary = consensus[0];
  const targetUpside =
    primary.target_price && lastClose && lastClose > 0
      ? ((primary.target_price - lastClose) / lastClose) * 100
      : null;
  const actionLine = consensusActionLine(primary.target_price ?? null, lastClose ?? null);

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-tight">
          🎯 애널리스트 컨센서스
        </h3>
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          {primary.fiscal_year}년 예상
        </span>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Tile
          label="목표주가"
          value={primary.target_price != null ? `${fmtKrw(primary.target_price)}원` : "—"}
          tone={targetUpside != null && targetUpside > 0 ? "good" : undefined}
          hint={
            targetUpside != null
              ? `현재가 대비 ${targetUpside > 0 ? "+" : ""}${targetUpside.toFixed(0)}%`
              : undefined
          }
        />
        <Tile
          label="예상 EPS"
          value={primary.consensus_eps != null ? `${fmtKrw(primary.consensus_eps)}원` : "—"}
          hint="주당순이익"
        />
        <Tile
          label="예상 매출"
          value={fmtEokFromMillion(primary.consensus_revenue)}
          hint={primary.fiscal_year + "년"}
        />
        <Tile
          label="예상 영업익"
          value={fmtEokFromMillion(primary.consensus_op_income)}
          hint={primary.fiscal_year + "년"}
        />
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">💡 {actionLine}</p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 2. 큰손 지분 (5% 보고)
// ─────────────────────────────────────────────────────────────────────

const HOLDER_TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  NPS: {
    label: "국민연금",
    cls: "bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/30",
  },
  AMC: {
    label: "자산운용",
    cls: "bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/30",
  },
  FUND: {
    label: "펀드",
    cls: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/30",
  },
  AFFILIATE: {
    // 계열사 — 그룹 내 cross-holding. 외부 큰손 아님 → 회색조로 톤다운.
    label: "계열사",
    cls: "bg-zinc-500/10 text-zinc-700 dark:text-zinc-300 border-zinc-500/30",
  },
  OTHER: {
    label: "기타",
    cls: "bg-muted text-muted-foreground border-border",
  },
};

export function HoldersCard({ holders }: { holders: InstitutionalOwnershipRow[] }) {
  if (!holders || holders.length === 0) return null;

  // 같은 보유자가 여러 번 신고했으면 가장 최근 행만 — 추세 가독성.
  const latestByHolder = new Map<string, InstitutionalOwnershipRow>();
  for (const r of holders) {
    if (!latestByHolder.has(r.holder_name)) latestByHolder.set(r.holder_name, r);
  }
  const rows = Array.from(latestByHolder.values())
    .sort((a, b) => (b.share_pct ?? 0) - (a.share_pct ?? 0))
    .slice(0, 6);

  const actionLine = holdersActionLine(rows);

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-tight">
          🐳 큰손 지분 (5% 보고)
        </h3>
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          최근 18 개월
        </span>
      </div>
      <ul className="space-y-1.5">
        {rows.map((r) => {
          const badge = HOLDER_TYPE_BADGE[r.holder_type] ?? HOLDER_TYPE_BADGE.OTHER;
          return (
            <li
              key={r.holder_name + r.reported_date}
              className="flex items-baseline justify-between gap-2 text-xs"
            >
              <div className="flex items-baseline gap-2 min-w-0">
                <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${badge.cls}`}>
                  {badge.label}
                </span>
                <span className="truncate text-foreground">{r.holder_name}</span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  ({r.reported_date})
                </span>
              </div>
              <span className="shrink-0 font-mono text-foreground">
                {fmtPct(r.share_pct)}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="text-xs leading-relaxed text-muted-foreground">💡 {actionLine}</p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 3. 실적 발표 예정
// ─────────────────────────────────────────────────────────────────────

const REPORT_LABEL: Record<string, string> = {
  Q1: "1 분기",
  Q2: "반기",
  Q3: "3 분기",
  FY: "연간 (사업보고서)",
};

export function EarningsCalendarCard({
  earnings,
}: {
  earnings: EarningsCalendarRow[];
}) {
  if (!earnings || earnings.length === 0) return null;
  const next = earnings[0];
  const days = daysFromToday(next.expected_date);
  const actionLine = earningsActionLine(days);

  return (
    <section className="rounded-xl border border-border bg-card p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold tracking-tight">
          📅 실적 발표 예정
        </h3>
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
          상장사 법정 기한
        </span>
      </div>
      <ul className="space-y-1.5">
        {earnings.map((e) => {
          const d = daysFromToday(e.expected_date);
          return (
            <li
              key={e.expected_date + e.report_type}
              className="flex items-baseline justify-between gap-2 text-xs"
            >
              <span className="text-foreground">
                {REPORT_LABEL[e.report_type] ?? e.report_type}
              </span>
              <span className="font-mono text-muted-foreground">
                {e.expected_date}{" "}
                <span className="text-[10px]">
                  ({d > 0 ? `D-${d}` : d === 0 ? "오늘" : `D+${-d}`})
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="text-xs leading-relaxed text-muted-foreground">💡 {actionLine}</p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────

function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "good" | "warn";
}) {
  const cls =
    tone === "good"
      ? "text-emerald-700 dark:text-emerald-300"
      : tone === "warn"
        ? "text-amber-700 dark:text-amber-300"
        : "text-foreground";
  return (
    <div className="rounded-md bg-muted/30 p-2.5 space-y-0.5">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm font-mono ${cls}`}>{value}</div>
      {hint && <div className="text-[10px] text-muted-foreground">{hint}</div>}
    </div>
  );
}
