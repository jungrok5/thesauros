/**
 * /guide — 직접 투자 전 5단계 절세·연금 셋팅.
 *
 * 톤: BookSummaryTable / MarketActionCard 와 동일.
 *   - 한눈 cheat-sheet 표 (5 row)
 *   - 단계별 카드는 컴팩트 — 한 줄 결론 + 안정형/공격형 한 줄 + CTA
 *   - 상세 (룰 grid / 꿀팁 / 주의)는 <details> 안에
 *   - 도메인 용어는 HelpTip popover
 *
 * 모든 수치 2026 한국 세법 기준. 면책: 정보 제공 목적, 결정은 본인 책임.
 */
import Link from "next/link";
import { ArrowLeft, AlertTriangle, ArrowRight, ChevronRight } from "lucide-react";
import { HelpTip } from "@/components/help-tip";

export const dynamic = "force-static";

interface Step {
  num: number;
  badge: string;            // 이모지
  title: string;
  effect: string;            // 핵심 절세 한 줄
  oneLine: string;           // 액션 한 줄
  conservative: string;
  aggressive: string;
  /** Optional 안전자산 30% — DB/DC + IRP only. */
  safetyAsset?: { conservative: string; aggressive: string };
  /** 1-line CTA button. */
  cta?: { href: string; label: string; external?: boolean };
  /** 펼침: 룰 grid */
  rules: Array<{ label: string; value: string; term?: string }>;
  tips: string[];
  warnings: string[];
}

const STEPS: Step[] = [
  {
    num: 1,
    badge: "🏢",
    title: "퇴직연금 — DB vs DC",
    effect: "퇴직소득세 30% 감면 (연금 수령 시)",
    oneLine: "임금 상승률 > 시장 수익률이면 DB 유지. 운용 자신 있으면 DC 전환.",
    conservative: "DB 유지 (회사 보장)",
    aggressive: "DC 전환 + 위험자산 70%",
    safetyAsset: {
      conservative: "TDF 2045/2050 (자동 자산배분)",
      aggressive: "ACE 미국30년국채액티브 + KODEX 종합채권액티브 (금리·신용 스프레드 활용)",
    },
    rules: [
      { label: "DB → DC 전환", value: "영구 (다시 DB X). 신중." },
      { label: "회사 적립금", value: "연봉의 1/12 이상" },
      { label: "위험자산 한도 (DC)", value: "70% / 안전자산 30% 의무" },
      { label: "수령", value: "55세+, 연금 형태 → 퇴직소득세 30% 감면", term: "tax_pension_30" },
    ],
    tips: [
      "퇴사 시 퇴직금 자동 IRP 이전 (의무). 연금 수령 → 퇴직소득세 30% 감면.",
      "DC 디폴트가 100% 안전자산이면 인플레 손해 — 위험자산 70% 채워 운용.",
    ],
    warnings: [
      "회사 폐업 시 DB는 일부만 보장 (DC는 본인 계좌라 무관).",
      "DC 환산금 (DB 적립금 → DC 이동 시) 정확성 확인.",
    ],
  },
  {
    num: 2,
    badge: "🐷",
    title: "연금저축",
    effect: "약 99만원/년 환급 (정부가 매년 주는 돈)",
    oneLine: "매월 50만원 자동이체 → 연 600만원 완납. 위험자산 100% 가능.",
    conservative: "TIGER 미국배당다우존스 + KOSEF 국고채10년",
    aggressive: "TIGER 미국S&P500 + TIGER 미국나스닥100",
    cta: {
      href: "https://www.bok.or.kr/portal/main/contents.do?menuNo=200459",
      label: "주거래 은행/증권사 앱에서 \"연금저축\" 검색",
      external: true,
    },
    rules: [
      { label: "세액공제 한도", value: "연 600만원 (13.2~16.5%)", term: "tax_credit_pension" },
      { label: "총 납입 한도", value: "연 1,800만원 (세공은 600까지)" },
      { label: "위험자산 한도", value: "100% (IRP보다 자유)" },
      { label: "수령", value: "55세+, 5년+, 연금소득세 3.3~5.5%" },
      { label: "중도해지", value: "기타소득세 16.5% + 세공 반환" },
    ],
    tips: [
      "ETF 매매 차익 비과세 (일반계좌 22% 양도세) — 미국 ETF에 최적.",
      "배당금도 인출 전까지 비과세 → 복리 효과.",
      "총급여 5,500 이하면 16.5% 환급 = 99만원, 초과면 13.2% = 79만원.",
    ],
    warnings: [
      "55세 이전 해지 = 사실상 손해. \"꺼낼 수 없는 돈\"으로 운용.",
      "초과 납입은 가능하지만 세공은 600만원까지만.",
    ],
  },
  {
    num: 3,
    badge: "💼",
    title: "IRP",
    effect: "추가 49만원/년 환급 (연금저축과 합산 900만원)",
    oneLine: "연금저축 풀 채운 후 +300만원. 위험자산 70% / 안전자산 30%.",
    conservative: "TDF 2045/2050 (자동 분산)",
    aggressive: "TIGER 미국S&P500 + 미국나스닥100",
    safetyAsset: {
      conservative: "ACE 단기채권 + KCD금리액티브",
      aggressive: "ACE 미국30년국채액티브 + KODEX 종합채권액티브 (단순 단기채보다 듀레이션·신용스프레드 활용)",
    },
    cta: {
      href: "https://www.bok.or.kr/portal/main/contents.do?menuNo=200459",
      label: "증권사 앱에서 \"IRP 개설\" 검색 (수수료 비교 권장)",
      external: true,
    },
    rules: [
      { label: "세액공제", value: "연금저축 + IRP 합산 연 900만원", term: "tax_credit_pension" },
      { label: "위험자산 한도", value: "70% / 안전자산 30% 의무" },
      { label: "수령", value: "55세+, 연금소득세 3.3~5.5%" },
      { label: "퇴직금 합산", value: "퇴직금 IRP 이전 → 퇴직소득세 30% 감면" },
    ],
    tips: [
      "ETF 매매 = 연금저축에 우선 배치 (위험자산 100% 가능). IRP는 채권·TDF·안전자산 위주.",
      "공격형 30% 안전자산은 액티브 채권 → 단순 단기채보다 1~3%p 추가 수익 가능.",
      "총급여 5,500 이하면 900만원 풀 납입 → 매년 약 148만원 환급 (월 12만원).",
    ],
    warnings: [
      "IRP 수수료 (운용·자산관리) 증권사별 다름 — 비교 필수.",
      "55세 이전 해지 = 16.5% 기타소득세 + 세공 반환.",
    ],
  },
  {
    num: 4,
    badge: "💰",
    title: "ISA",
    effect: "이익 200만원 비과세 + 초과 9.9% 분리과세",
    oneLine: "연 2,000만원 / 총 1억원 / 3년 의무. 만기 → 연금저축 이전 시 +40만원 보너스.",
    conservative: "예금형 + 배당 ETF + 채권 ETF",
    aggressive: "한국 성장 ETF + 미국 S&P500/QQQ ETF + 개별주",
    cta: {
      href: "https://www.bok.or.kr/portal/main/contents.do?menuNo=200459",
      label: "주거래 증권사에서 \"중개형 ISA\" 개설",
      external: true,
    },
    rules: [
      { label: "납입 한도", value: "연 2,000만원, 총 1억원 (미사용 이월)" },
      { label: "비과세", value: "이익 200만원 (서민/농어민 400만원)", term: "isa_tax" },
      { label: "초과 분리과세", value: "9.9% (일반계좌 15.4%보다 5.5%p ↓)" },
      { label: "의무 가입", value: "3년" },
      { label: "운용 가능", value: "ETF, 주식, ELS, RP, 예적금" },
    ],
    tips: [
      "★★★ 만기 → 연금저축 이전 시 추가 300만원 세액공제 (1회성, 약 40만원 환급).",
      "3년 풍차돌리기: 매년 ISA 신규 가입 → 3년 만기 도래 → 비과세 받고 다음 ISA로.",
      "중개형 (본인 운용) vs 신탁형/일임형 — 책 정신상 중개형.",
    ],
    warnings: [
      "ISA 손실은 다른 계좌 손익과 통산 X — 손실 위험 큰 종목은 일반계좌.",
      "미국 주식 직접 매매 불가 — 미국 ETF (한국 상장)로 노출.",
    ],
  },
  {
    num: 5,
    badge: "📈",
    title: "직접 투자",
    effect: "이 사이트의 본 영역 — 책 정신 자동 분석",
    oneLine: "위 4단계 채운 후 잉여 자금으로. 종목 검색 → 정리표 → 매수/청산 신호.",
    conservative: "연금/ISA 80% + 직접투자 20%",
    aggressive: "연금/ISA 50% + 직접투자 50%",
    cta: { href: "/stocks", label: "종목 검색 시작" },
    rules: [
      { label: "한국 양도세", value: "X (대주주 제외), 배당 15.4%" },
      { label: "미국 양도세", value: "22% (연 250만원 공제 후), 배당 15%" },
      { label: "환차익", value: "5천만원 초과 시 신고" },
      { label: "거래시간", value: "한국 09:00-15:30 / 미국 23:30-06:00 KST" },
    ],
    tips: [
      "관심 종목 추가 → 자동 분석 + 텔레그램 알림. 매수/청산 시그널 놓치지 X.",
      "책 정신: 종목보다 타이밍. 정배열 + 240MA 위 + 8주 트레일링 +50% 안 + 캔들 신호.",
    ],
    warnings: [
      "선물·옵션·레버리지 X — 책 원칙.",
      "신용·미수 거래 X — 자본 보전 1순위.",
    ],
  },
];

interface CheatRow {
  step: string;
  effect: string;
  cap: string;
  note: string;
}
const CHEAT: CheatRow[] = [
  { step: "1. 퇴직연금 DC",   effect: "퇴직소득세 30% 감면",        cap: "연봉의 1/12",   note: "위험 70% / 안전 30%" },
  { step: "2. 연금저축",      effect: "약 99만원/년",              cap: "연 600만원",   note: "위험 100% 가능" },
  { step: "3. IRP",          effect: "추가 49만원/년 (합산 148)", cap: "추가 300만원",  note: "위험 70% / 안전 30%" },
  { step: "4. ISA",          effect: "200만원 비과세 + 40만원*",   cap: "연 2,000 / 1억", note: "*만기 연금이전" },
  { step: "5. 직접투자",      effect: "한국 X · 미국 22%",          cap: "잉여 자금",    note: "이 사이트 핵심" },
];

function StepCard({ s }: { s: Step }) {
  return (
    <article className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Compact header — one-glance summary */}
      <header className="px-4 py-3 border-b border-border bg-muted/20">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
              단계 {s.num} / 5
            </div>
            <h2 className="text-base font-semibold tracking-tight">
              {s.badge} {s.title}
            </h2>
          </div>
          <div className="text-sm font-medium text-emerald-700 dark:text-emerald-300">
            {s.effect}
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
          {s.oneLine}
        </p>
      </header>

      {/* 안정형 / 공격형 한 줄 */}
      <table className="w-full text-xs">
        <tbody>
          <tr className="border-b border-border">
            <td className="px-4 py-2 align-top w-24 md:w-32 text-[10px] uppercase tracking-wider text-muted-foreground">
              🛡️ 안정형
            </td>
            <td className="px-4 py-2 align-top">{s.conservative}</td>
          </tr>
          <tr className="border-b border-border bg-muted/10">
            <td className="px-4 py-2 align-top w-24 md:w-32 text-[10px] uppercase tracking-wider text-muted-foreground">
              ⚡ 공격형
            </td>
            <td className="px-4 py-2 align-top">{s.aggressive}</td>
          </tr>
          {s.safetyAsset && (
            <>
              <tr className="border-b border-border">
                <td className="px-4 py-2 align-top w-24 md:w-32 text-[10px] uppercase tracking-wider text-muted-foreground">
                  🛡️ 안전자산 30% (안정)
                </td>
                <td className="px-4 py-2 align-top">{s.safetyAsset.conservative}</td>
              </tr>
              <tr className="border-b border-border bg-muted/10">
                <td className="px-4 py-2 align-top w-24 md:w-32 text-[10px] uppercase tracking-wider text-muted-foreground">
                  ⚡ 안전자산 30% (공격)
                </td>
                <td className="px-4 py-2 align-top">{s.safetyAsset.aggressive}</td>
              </tr>
            </>
          )}
        </tbody>
      </table>

      {/* CTA + Expand toggle */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-t border-border bg-muted/10">
        {s.cta && (
          s.cta.external ? (
            <a
              href={s.cta.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-3 py-1.5 text-xs hover:bg-muted"
            >
              {s.cta.label}
              <ArrowRight className="h-3 w-3" />
            </a>
          ) : (
            <Link
              href={s.cta.href}
              className="inline-flex items-center gap-1.5 rounded-md border-2 border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300 hover:opacity-90"
            >
              {s.cta.label}
              <ArrowRight className="h-3 w-3" />
            </Link>
          )
        )}
        <details className="ml-auto">
          <summary className="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs cursor-pointer hover:bg-muted list-none">
            <span>세부 룰 · 꿀팁 · 주의</span>
            <ChevronRight className="h-3 w-3 transition-transform duration-150 ease-out [details[open]_&]:rotate-90" />
          </summary>
          <div className="absolute mt-2 right-4 left-4 z-10 rounded-lg border border-border bg-card shadow-xl p-4 space-y-3 text-xs">
            {/* Rules grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {s.rules.map((r) => (
                <div key={r.label} className="flex items-start gap-2 rounded border border-border bg-muted/10 px-2 py-1.5">
                  <span className="font-medium text-muted-foreground shrink-0 min-w-[6.5rem]">
                    {r.term ? <HelpTip term={r.term}>{r.label}</HelpTip> : r.label}
                  </span>
                  <span>{r.value}</span>
                </div>
              ))}
            </div>
            {/* Tips */}
            {s.tips.length > 0 && (
              <div className="rounded border border-sky-500/30 bg-sky-500/5 p-2 space-y-1">
                <div className="text-[11px] font-semibold text-sky-700 dark:text-sky-300">💡 꿀팁</div>
                <ul className="space-y-1 leading-relaxed">
                  {s.tips.map((t, i) => (
                    <li key={i} className="flex gap-1.5">
                      <span className="text-sky-600 dark:text-sky-400">·</span>
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {/* Warnings */}
            {s.warnings.length > 0 && (
              <div className="rounded border border-rose-500/30 bg-rose-500/5 p-2 space-y-1">
                <div className="text-[11px] font-semibold text-rose-700 dark:text-rose-300">⚠ 주의</div>
                <ul className="space-y-1 leading-relaxed">
                  {s.warnings.map((w, i) => (
                    <li key={i} className="flex gap-1.5">
                      <span className="text-rose-600 dark:text-rose-400">·</span>
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </details>
      </div>
    </article>
  );
}

export default function GuidePage() {
  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          🗺️ 절세·연금 가이드
        </h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          직접 투자 전 거쳐야 할 5단계. 다 안 하면 매년 정부가 주는{" "}
          <strong className="text-foreground">약 148만원 + ISA 40만원</strong>{" "}
          놓침. 한국 2026 세법 기준.
        </p>
        <div className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/5 px-2 py-1 text-[11px] text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-3 w-3" />
          정보 제공 목적 · 투자 결정은 본인 책임
        </div>
      </header>

      {/* 한눈에 — cheat sheet */}
      <section className="rounded-xl border border-border bg-card overflow-hidden">
        <header className="px-4 py-2.5 border-b border-border bg-muted/30">
          <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
            🗺️ 한눈에 — 5단계 절세 지도
          </h2>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/20">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">단계</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">절세 효과</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">한도</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">비고</th>
              </tr>
            </thead>
            <tbody>
              {CHEAT.map((row, i) => (
                <tr
                  key={row.step}
                  className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
                >
                  <td className="px-3 py-2 align-top font-medium whitespace-nowrap">{row.step}</td>
                  <td className="px-3 py-2 align-top">{row.effect}</td>
                  <td className="px-3 py-2 align-top text-muted-foreground">{row.cap}</td>
                  <td className="px-3 py-2 align-top text-muted-foreground">{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* 5 steps */}
      <div className="space-y-3">
        {STEPS.map((s) => (
          <StepCard key={s.num} s={s} />
        ))}
      </div>

      {/* Final CTA */}
      <section className="rounded-xl border-2 border-emerald-500/40 bg-emerald-500/5 p-5 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-emerald-700 dark:text-emerald-300">
          5단계 모두 셋팅 완료했다면
        </div>
        <h2 className="text-lg font-semibold tracking-tight">
          이제 직접 투자 — 책 정신으로 한 종목씩 분석.
        </h2>
        <div className="flex flex-wrap gap-2 pt-1">
          <Link
            href="/stocks"
            className="inline-flex items-center gap-1.5 rounded-md border-2 border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-700 dark:text-emerald-300 hover:opacity-90"
          >
            종목 검색 시작
            <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/glossary"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            용어집 보기
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>
    </div>
  );
}
