/**
 * /glossary — 책 용어집 + 시스템 신호 사전.
 *
 * 책 (캔들차트 추세추종)에서 쓰는 한국어 매매 용어를 한 페이지에 모음.
 * HelpTip이 같은 데이터를 사용 — 표 안의 (?) / 밑줄 부분을 누르면 같은
 * 설명이 popover로, 더 깊이 보려면 이 페이지로 와서 카테고리별로 통람.
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { GLOSSARY } from "@/lib/glossary";

export const dynamic = "force-static";

// Grouped sections (manual curation, simpler than auto-grouping by key prefix).
const SECTIONS: Array<{
  heading: string;
  description?: string;
  keys: string[];
}> = [
  {
    heading: "📈 책의 차트 패턴",
    description: "캔들차트 추세추종에서 진입 / 청산 신호로 쓰이는 8가지 + 변형 패턴.",
    keys: [
      "ssang_badak", "short_term_double_bottom", "reverse_h_and_s",
      "cup_with_handle", "dolbanji_240ma", "flag", "ascending_triangle",
    ],
  },
  {
    heading: "🕯️ 캔들 종류",
    description: "한 봉으로 시장 심리를 읽는 책의 캔들 분류.",
    keys: [
      "yangbong", "eumbong",
      "jangdae_yangbong", "jangdae_eumbong",
      "nunsseop_candle",
      "gura_candle", "yangpalbong", "hidden_jangdae", "jugobatgo_candle",
      "catalyst_candle",
      "hooking_candle", "reaper_candle",
    ],
  },
  {
    heading: "📊 거래량 12 케이스 (책 p364)",
    description: "거래량 + 가격 위치 + 추세 방향 조합으로 시장 단계 분류.",
    keys: [
      "volume_case_generic",
      "volume_case_0", "volume_case_1", "volume_case_2", "volume_case_3",
      "volume_case_4", "volume_case_5", "volume_case_6", "volume_case_7",
      "volume_case_8", "volume_case_9", "volume_case_10",
      "volume_case_11", "volume_case_12",
      "reverse_accumulation",
    ],
  },
  {
    heading: "🎯 4등분선 매매 (책의 시그너처)",
    description: "장대양봉 catalyst의 몸통을 4등분해 어디에 있는지로 매매 결정.",
    keys: [
      "safe_zone_75",
      "quarter_safe75", "quarter_warn50", "quarter_danger25", "quarter_broken",
    ],
  },
  {
    heading: "📐 보조 지표 (RSI / MACD)",
    description: "책은 보조 신호로만 취급 — 캔들 / 가격 / 거래량의 corroboration 도구.",
    keys: ["rsi", "macd", "macd_divergence"],
  },
  {
    heading: "🛡️ 안전 게이트 + 무효화 룰",
    description: "추세 후반부에서 매수 자리를 지키는 책 정신상 자동 강등 로직.",
    keys: [
      "stretch_reason", "pattern_invalidation",
      "rally_8w", "pos_52w", "ma_240_distance",
    ],
  },
  {
    heading: "⏰ 시간프레임",
    description: "책은 주봉/월봉을 우선, 일봉은 보조.",
    keys: ["tf_daily", "tf_weekly", "tf_monthly"],
  },
  {
    heading: "🚦 시스템 액션 라벨",
    description: "BookVerdict 카드와 watchlist 칩의 의미.",
    keys: ["action_strong_buy", "action_buy", "action_avoid", "action_sell"],
  },
  {
    heading: "🌍 거시 + 시장 레짐",
    description: "대시보드에 보이는 거시 지표 / 시장 심리 사이클.",
    keys: [
      "macro_liquidity", "macro_rate", "macro_cycle", "macro_price", "macro_fear",
      "regime_hope", "regime_fear", "regime_despair",
      "mv_pq", "tips_spread", "ppi_yoy", "cpi_yoy", "vix_state", "yield_curve",
    ],
  },
  {
    heading: "💰 절세·연금 (한국 2026 세법)",
    description: "직접 투자 전 거쳐야 할 5단계 셋팅의 세제 용어.",
    keys: ["tax_pension_30", "tax_credit_pension", "isa_tax", "tax_isa_to_pension"],
  },
];

export default function GlossaryPage() {
  // Find any glossary keys not covered by any section so the page stays
  // exhaustive even after future additions.
  const covered = new Set(SECTIONS.flatMap((s) => s.keys));
  const orphans = Object.keys(GLOSSARY).filter((k) => !covered.has(k));

  return (
    <div className="space-y-8 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">📚 용어집</h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          책 (캔들차트 추세추종) + 시스템에서 쓰는 한국어 매매 용어 정리. 페이지
          곳곳에 있는 점선 밑줄 / 물음표 (?) 아이콘을 눌러도 같은 설명이 popover
          로 나옵니다. 더 깊이 보고싶을 때는 여기 와서 카테고리별로 살펴보세요.
        </p>
      </header>

      {SECTIONS.map((section) => (
        <section key={section.heading} className="space-y-3">
          <header>
            <h2 className="text-base font-semibold tracking-tight">
              {section.heading}
            </h2>
            {section.description && (
              <p className="text-xs text-muted-foreground mt-1">
                {section.description}
              </p>
            )}
          </header>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {section.keys
              .filter((k) => GLOSSARY[k] != null)
              .map((k) => {
                const entry = GLOSSARY[k];
                return (
                  <article
                    key={k}
                    id={k}
                    className="rounded-lg border border-border bg-card p-4 scroll-mt-20"
                  >
                    <h3 className="font-medium text-sm">{entry.title}</h3>
                    <p className="mt-2 text-xs text-muted-foreground whitespace-pre-line leading-relaxed">
                      {entry.body}
                    </p>
                    {entry.link && (
                      <a
                        href={entry.link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-2 inline-block text-[11px] text-sky-600 dark:text-sky-400 hover:underline"
                      >
                        {entry.link.label ?? "더 알아보기 →"}
                      </a>
                    )}
                  </article>
                );
              })}
          </div>
        </section>
      ))}

      {orphans.length > 0 && (
        <section className="space-y-3">
          <header>
            <h2 className="text-base font-semibold tracking-tight text-muted-foreground">
              ⋯ 기타
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              섹션에 아직 분류되지 않은 용어들.
            </p>
          </header>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {orphans.map((k) => {
              const entry = GLOSSARY[k];
              return (
                <article
                  key={k}
                  id={k}
                  className="rounded-lg border border-border bg-card p-4 scroll-mt-20"
                >
                  <h3 className="font-medium text-sm">{entry.title}</h3>
                  <p className="mt-2 text-xs text-muted-foreground whitespace-pre-line leading-relaxed">
                    {entry.body}
                  </p>
                </article>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
