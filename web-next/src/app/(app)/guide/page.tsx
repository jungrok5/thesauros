/**
 * /guide — 직접 투자 전 절세·연금 셋팅 5단계.
 *
 * 톤: BookSummaryTable / MarketActionCard 동일.
 *   - 한눈 cheat-sheet 표 (5 row)
 *   - 자산 × 계좌 매칭 매트릭스 (어떤 ETF가 어느 계좌에 유리한가)
 *   - 🎯 위험도 3-tier 종목 표 (안정형 / 균형형 / 공격형 × 위험자산 + 안전자산)
 *   - 3-tier × 계좌별 매핑 (각 위험도가 어느 계좌에서 가장 유리한가)
 *   - 단계별 카드는 컴팩트 — 단계 특이사항 + 세부는 details 펼침
 *   - 도메인 용어는 HelpTip popover
 *
 * 모든 수치 2026 한국 세법 기준. 면책: 정보 제공 목적, 결정은 본인 책임.
 */
import Link from "next/link";
import { ArrowLeft, AlertTriangle, ArrowRight, ChevronRight } from "lucide-react";
import { HelpTip } from "@/components/help-tip";

// NB: `dynamic = "force-static"` was here, but it conflicted with the
// (app)/layout.tsx auth() check — at build time `auth()` returns null →
// `redirect("/login")` got baked into the static HTML. Hard refresh then
// served that cached redirect. Content is constants only; Next.js infers
// optimization without forcing static.

// ─────────────────────────────────────────────────────────────────────
// 1. 한눈 cheat-sheet
// ─────────────────────────────────────────────────────────────────────
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

// ─────────────────────────────────────────────────────────────────────
// 2. 🎯 위험도 3 tier (안정형 / 균형형 / 공격형)
// ─────────────────────────────────────────────────────────────────────
//
// 이전 "자산 × 계좌 매트릭스" (7행 × 5열) 섹션은 2026-05-20 제거 —
// 사용자가 "두 군데에 같은 정보, 헷갈린다" 지적. 아래 TIER_ACCOUNT_MAP
// (위험도 × 계좌별 + 구체 종목명) 이 같은 정보를 actionable 한 형태로
// 이미 담고 있어 중복. 한 군데로 통합.
// ─────────────────────────────────────────────────────────────────────
//
// 사용자 톤 명확화: 직접투자자 시점에서 S&P500 = 안정형 (시장 평균).
// 더 보수는 채권/배당 ETF, 더 공격은 나스닥/섹터 ETF.
interface TierRow {
  type: "안정형" | "균형형" | "공격형";
  emoji: string;
  label: string;
  tone: "safe" | "balanced" | "aggressive";
  product: string;
  why: string;
}

// 위험자산 — 연금/IRP/ISA 위험자산 슬롯 + 직접투자 핵심
const RISK_TIERS: TierRow[] = [
  {
    type: "안정형",
    emoji: "🟢",
    label: "시장 평균 (지수+배당)",
    tone: "safe",
    product: "TIGER 미국S&P500 + KODEX 미국배당다우존스",
    why: "미국 대형주 500 지수 + 배당 보조. 직접 투자자의 \"기본\" — 정배열 + 240MA 위 자동 만족.",
  },
  {
    type: "균형형",
    emoji: "🟡",
    label: "성장 지수 (시장+α)",
    tone: "balanced",
    product: "TIGER 미국나스닥100 + TIGER K-반도체",
    why: "기술주 비중 ↑, 변동성 시장보다 큼. 한국 주력 산업(반도체)도 일부.",
  },
  {
    type: "공격형",
    emoji: "🔴",
    label: "빅테크/섹터 집중",
    tone: "aggressive",
    product: "TIGER 미국테크TOP10 INDXX + TIGER 미국필라델피아반도체나스닥",
    why: "빅테크 10종목 / 반도체 SOX 집중. 강세 사이클 큰 수익, 약세 -40~50% 가능.",
  },
];

// 안전자산 30% (IRP / DC 의무) — \"이 슬롯에 무엇을 채울 것인가\"
const SAFE_TIERS: TierRow[] = [
  {
    type: "안정형",
    emoji: "🟢",
    label: "단기채 / 종합채권",
    tone: "safe",
    product: "KCD금리액티브 또는 KODEX 종합채권액티브",
    why: "변동성 거의 없음. 안전자산 30% 의무 채우는 기본.",
  },
  {
    type: "균형형",
    emoji: "🟡",
    label: "듀레이션 활용",
    tone: "balanced",
    product: "ACE 미국30년국채액티브",
    why: "장기 미국채. 금리 인하 사이클에 채권 가격 ↑ → 자본이득 추구.",
  },
  {
    type: "공격형",
    emoji: "🔴",
    label: "혼합형 (실제 주식 +15%p 우회)",
    tone: "aggressive",
    product: "1Q 미국나스닥100미국채혼합50액티브",
    why: "나스닥100 50% + 미국채 50%. 안전자산 카테고리지만 실제 주식 노출 → IRP/DC 위험자산 70% 한도를 사실상 85%로 우회.",
  },
];

const TIER_TONE: Record<TierRow["tone"], { border: string; text: string; bg: string }> = {
  safe:       { border: "border-emerald-500/40", text: "text-emerald-700 dark:text-emerald-300", bg: "bg-emerald-500/5" },
  balanced:   { border: "border-amber-500/40",   text: "text-amber-700 dark:text-amber-300",     bg: "bg-amber-500/5" },
  aggressive: { border: "border-rose-500/40",    text: "text-rose-700 dark:text-rose-300",       bg: "bg-rose-500/5" },
};

// 계좌별 매핑 — 3 tier 위험자산 종목을 어디서 사야 가장 유리한가
interface TierAccountRow {
  type: string;
  pension: string;       // 연금/IRP/DC
  isa: string;
  general: string;
}
const TIER_ACCOUNT_MAP: TierAccountRow[] = [
  {
    type: "🟢 안정형",
    pension: "TIGER 미국S&P500 + KODEX 미국배당 ⭐\n매매차익·배당 비과세",
    isa: "동일 + 한국 배당주 (KT&G, KB금융 등)\n200만 비과세",
    general: "VOO (S&P500 직접) · SCHD ⭐\n운용보수 0.03~0.06%",
  },
  {
    type: "🟡 균형형",
    pension: "TIGER 미국나스닥100 + TIGER K-반도체 ⭐",
    isa: "동일 + 한국 성장주 (이 사이트 분석 종목) ⭐⭐\n200만 비과세",
    general: "QQQ (나스닥100 직접) + 미국 개별주 ⭐\n(애플·MS·구글)",
  },
  {
    type: "🔴 공격형",
    pension: "TIGER 미국테크TOP10 INDXX + 미국필라델피아반도체나스닥 ⭐",
    isa: "동일 + 한국 반도체 개별주 (SK하이닉스 등)",
    general: "SOXX (SOX 직접) + 미국 개별주 ⭐⭐\n(엔비디아·테슬라·AMD)",
  },
];

// ─────────────────────────────────────────────────────────────────────
// 4. 5단계 카드
// ─────────────────────────────────────────────────────────────────────
interface Step {
  num: number;
  badge: string;
  title: string;
  effect: string;
  oneLine: string;
  /** 단계별 특이사항 (이전 conservative/aggressive 대신) */
  highlight: string;
  /** 위 3-tier 표 안에서 어떤 슬롯을 채워야 하는지 안내 */
  slots: { label: string; hint: string }[];
  cta?: { href: string; label: string; external?: boolean };
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
    highlight: "DC 전환 시 위 3-tier (안정형/균형형/공격형) 표에서 본인 위험도 선택. 안전자산 30%도 같은 3-tier 중 선택.",
    slots: [
      { label: "위험자산 70%", hint: "위 위험자산 안정형/균형형/공격형 중 본인 위험 성향 선택" },
      { label: "안전자산 30% (의무)", hint: "위 안전자산 안정형/균형형/공격형 중 선택. 공격형(1Q 혼합형)이면 사실상 위험자산 85% 효과." },
    ],
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
    highlight: "IRP보다 자유 — 안전자산 의무 X. 위 위험자산 안정형/균형형/공격형 중 본인 선택해 100% 운용.",
    slots: [
      { label: "위험자산 100%", hint: "위 위험자산 안정형/균형형/공격형 중 선택. 안전자산 의무 X." },
    ],
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
      "★★★ 자동매수/적립식 ETF 설정 — 매월 1일/25일 같은 날 자동매수 → 책 정신의 \"분할 진입\" + 변동성 평균화. 인간 심리(공포·욕심)에 휘둘리지 X.",
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
    highlight: "안전자산 30% 의무 → 공격형 (1Q 혼합형) 선택 시 실제 주식 노출 +15%p 우회 가능 → 사실상 위험자산 85%.",
    slots: [
      { label: "위험자산 70%", hint: "위 위험자산 안정형/균형형/공격형 중 선택" },
      { label: "안전자산 30% (의무)", hint: "위 안전자산 안정형/균형형/공격형 중 선택. 공격형은 사실상 위험자산 85% 효과." },
    ],
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
      "★★★ 자동이체 + 자동매수 한 번에 설정 — 월급일에 IRP 자동 입금 → 정해진 ETF 자동 매수. 손 안 대고 5년 굴리면 책 정신상 \"버티기\" 자동 실행.",
      "ETF 매매 = 연금저축에 우선 배치 (위험자산 100% 가능). IRP는 채권·TDF·안전자산 위주.",
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
    highlight: "위 위험자산 안정형/균형형/공격형 중 본인 선택 + ISA만의 추가 옵션 = 한국 개별주 (200만원 비과세 효과 큼).",
    slots: [
      { label: "ETF 자유", hint: "위 위험자산 안정형/균형형/공격형 중 선택" },
      { label: "한국 개별주 (ISA 한정)", hint: "200만원 비과세 활용 — 일반계좌 대비 유리. 미국 주식 직접 매매는 불가." },
    ],
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
    highlight: "일반계좌만 미국 직접 ETF/주식 매매 가능. 환율 + 양도세 22% 감안. 비중은 본인 위험 성향에 따라 (위 3-tier 참고).",
    slots: [
      { label: "비중 (위험도별)", hint: "안정형: 연금/ISA 80% + 직접 20% · 균형형/공격형: 50:50 가능" },
      { label: "미국 직접 ETF/주식", hint: "SPY/QQQ/개별주 — 일반계좌 한정. 양도세 22% (250만원 공제)." },
    ],
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

// ─────────────────────────────────────────────────────────────────────
// 5. 증권사 메뉴 위치
// ─────────────────────────────────────────────────────────────────────
interface BrokerRow {
  name: string;
  app: string;
  pensionPath: string;
  isaPath: string;
  autoBuy: string;
}
const BROKERS: BrokerRow[] = [
  { name: "미래에셋증권",  app: "M-STOCK",          pensionPath: "메뉴 → 연금 → 연금저축펀드/IRP",       isaPath: "메뉴 → ISA → 중개형 ISA",       autoBuy: "종목 화면 → 자동주문 → 정기매수" },
  { name: "NH투자증권",   app: "나무·QV",          pensionPath: "메뉴 → 연금 → 연금저축계좌/IRP",      isaPath: "메뉴 → ISA → 중개형",          autoBuy: "종목 → 자동매매 → 적립식" },
  { name: "한국투자증권", app: "한국투자 (eFriend)", pensionPath: "전체 메뉴 → 연금 → 연금저축/IRP",     isaPath: "전체 메뉴 → ISA 계좌",          autoBuy: "주식 → 자동매수 설정" },
  { name: "삼성증권",     app: "mPOP",             pensionPath: "메뉴 → 자산관리 → 연금 → 연금저축/IRP", isaPath: "메뉴 → 자산관리 → ISA",         autoBuy: "ETF 주문 → 정기자동매수" },
  { name: "키움증권",     app: "영웅문S/영웅문S#",   pensionPath: "좌측 메뉴 → 연금/ISA → 연금저축/IRP",  isaPath: "좌측 메뉴 → 연금/ISA → 중개형 ISA", autoBuy: "주식 → 자동매매 → 적립식 매수" },
];


// ─────────────────────────────────────────────────────────────────────
// Components
// ─────────────────────────────────────────────────────────────────────

function StepCard({ s }: { s: Step }) {
  return (
    <article className="rounded-xl border border-border bg-card overflow-hidden">
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
        <p className="mt-1 text-xs leading-relaxed">
          <span className="opacity-70">단계 특이사항:</span> {s.highlight}
        </p>
      </header>

      {/* 슬롯 — 어떤 위 3-tier 표를 어디에 적용할지 */}
      <table className="w-full text-xs">
        <tbody>
          {s.slots.map((slot, i) => (
            <tr key={slot.label} className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}>
              <td className="px-4 py-2 align-top w-32 md:w-40 text-[11px] font-medium">
                {slot.label}
              </td>
              <td className="px-4 py-2 align-top text-muted-foreground">{slot.hint}</td>
            </tr>
          ))}
        </tbody>
      </table>

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

function TierTable({ title, rows }: { title: string; rows: TierRow[] }) {
  return (
    <div className="rounded-lg border border-border overflow-hidden">
      <header className="px-3 py-2 border-b border-border bg-muted/30">
        <h3 className="text-xs font-semibold tracking-wide">{title}</h3>
      </header>
      <table className="w-full text-xs">
        <tbody>
          {rows.map((r) => {
            const tone = TIER_TONE[r.tone];
            return (
              <tr key={r.type} className={`border-b border-border last:border-b-0 ${tone.bg}`}>
                <td className="px-3 py-2 align-top w-24 md:w-28">
                  <div className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md border-2 ${tone.border} text-xs font-medium ${tone.text}`}>
                    <span>{r.emoji}</span>
                    <span>{r.type}</span>
                  </div>
                  <div className={`mt-1 text-[10px] ${tone.text} opacity-80`}>{r.label}</div>
                </td>
                <td className="px-3 py-2 align-top">
                  <div className="text-sm font-medium">{r.product}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground leading-relaxed">{r.why}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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

      {/* 한눈 cheat-sheet */}
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

      {/* 🎯 위험도 3-tier 종목 추천 — 이전엔 위에 "자산 × 계좌
          매트릭스" (7행 × 5열) 가 추가로 있었지만, 같은 정보가 아래
          "위험도 × 계좌별 매핑" 에 더 actionable 형태 (구체 종목명
          포함) 로 있어 중복이라 제거 (2026-05-20). */}
      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <header>
          <h2 className="text-base font-semibold tracking-tight">🎯 위험도별 종목 추천 (안정형 · 균형형 · 공격형)</h2>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            본인 위험 성향에 맞는 한 줄 선택. 5단계 카드 각각에서 &quot;위 안정형/균형형/공격형 중 선택&quot;으로 참조.
            직접 투자자 시점에서 S&amp;P500 = 안정형 (시장 평균), 나스닥100 = 균형형, 빅테크/반도체 집중 = 공격형.
          </p>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <TierTable title="📈 위험자산 (연금/IRP/ISA · 본 운용 영역)" rows={RISK_TIERS} />
          <TierTable title="🛡️ 안전자산 30% (IRP/DC 의무 슬롯)" rows={SAFE_TIERS} />
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">
          ⚡ <strong>꿀팁</strong>: 안전자산 30%에서 <strong>공격형 (1Q 미국나스닥100미국채혼합50액티브)</strong>를 선택하면 안전자산 카테고리이지만
          실제 주식 50% 포함 → IRP/DC 위험자산 70% 한도를 사실상 85%로 우회. 공격형 셋업의 필수 도구.
        </p>
      </section>

      {/* 위험도 × 계좌별 매핑 — 같은 위험도라도 계좌에 따라 유리한 종목이 다르다 */}
      <section className="rounded-xl border border-border bg-card overflow-hidden">
        <header className="px-4 py-2.5 border-b border-border bg-muted/30">
          <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
            🧭 위험도 × 계좌별 매핑 — 같은 위험도, 다른 계좌 → 다른 최적 종목
          </h2>
          <p className="text-[10px] text-muted-foreground/80 mt-1">
            ⭐ = 절세 우위 · ⭐⭐ = 강력 추천 · 같은 위험도라도 계좌가 다르면 매매차익 비과세 / 양도세 / 배당세 효과 다름.
          </p>
        </header>
        {/* Desktop: 4열 매트릭스 — md+ */}
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/20">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground min-w-[110px]">위험도</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">연금/IRP/DC</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">ISA (중개형)</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">일반계좌</th>
              </tr>
            </thead>
            <tbody>
              {TIER_ACCOUNT_MAP.map((row, i) => (
                <tr key={row.type} className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}>
                  <td className={`px-3 py-2 align-top font-medium whitespace-nowrap ${i % 2 === 1 ? "bg-muted/10" : "bg-card"}`}>
                    {row.type}
                  </td>
                  <td className="px-3 py-2 align-top whitespace-pre-line">{row.pension}</td>
                  <td className="px-3 py-2 align-top whitespace-pre-line">{row.isa}</td>
                  <td className="px-3 py-2 align-top whitespace-pre-line">{row.general}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile: 위험도별 카드 */}
        <ul className="md:hidden divide-y divide-border">
          {TIER_ACCOUNT_MAP.map((row) => (
            <li key={row.type} className="px-3 py-3 space-y-2">
              <div className="text-xs font-semibold">{row.type}</div>
              <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 text-[11px]">
                <dt className="text-muted-foreground">연금/IRP/DC</dt>
                <dd className="whitespace-pre-line leading-relaxed">{row.pension}</dd>
                <dt className="text-muted-foreground">ISA</dt>
                <dd className="whitespace-pre-line leading-relaxed">{row.isa}</dd>
                <dt className="text-muted-foreground">일반계좌</dt>
                <dd className="whitespace-pre-line leading-relaxed">{row.general}</dd>
              </dl>
            </li>
          ))}
        </ul>

        <footer className="px-4 py-2 border-t border-border bg-muted/10 text-xs text-muted-foreground leading-relaxed">
          💡 핵심: <strong className="text-foreground">국내 상장 미국 ETF는 연금/IRP에서 매매차익 0%</strong>, ISA에서는 한국 개별주 200만 비과세 활용,
          일반계좌만 미국 직접 ETF/주식 가능 (양도세 22% · 연 250만 공제).
        </footer>
      </section>

      {/* 5 steps */}
      <div className="space-y-3">
        {STEPS.map((s) => (
          <StepCard key={s.num} s={s} />
        ))}
      </div>

      {/* 자동매수/적립식 박스 */}
      <section className="rounded-xl border-2 border-sky-500/40 bg-sky-500/5 p-5 space-y-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-sky-700 dark:text-sky-300">
            ★★★ 가장 강력한 한 가지
          </div>
          <h2 className="text-lg font-semibold tracking-tight mt-1">
            🔁 자동이체 + 자동매수 (적립식) 한 번 설정 → 평생 굴림
          </h2>
        </div>
        <p className="text-sm leading-relaxed">
          연금저축 / IRP는 매월 정해진 날에 자동이체 + 자동매수 (적립식 ETF) 설정 한 번
          해두면 손 안 대고 운용 가능. 매월 동일 금액 매수 = <strong>분할 진입</strong>
          (책 정신: 한 번에 다 사지 X, 분할로). 변동성 평균화 + 인간 심리(공포·욕심)에 휘둘리지 X.
        </p>
        <ul className="text-xs space-y-1 text-foreground/85">
          <li className="flex gap-2"><span className="text-sky-600 dark:text-sky-400 shrink-0">·</span><span><strong>자동이체</strong>: 월급일(예: 25일) → 연금저축 + IRP 계좌로 자동 입금</span></li>
          <li className="flex gap-2"><span className="text-sky-600 dark:text-sky-400 shrink-0">·</span><span><strong>자동매수</strong>: 입금일 다음날 = 정해진 ETF 자동 매수 (위 3-tier 안정형/균형형/공격형 중 본인 선택)</span></li>
          <li className="flex gap-2"><span className="text-sky-600 dark:text-sky-400 shrink-0">·</span><span><strong>분기에 한 번 확인</strong>: 비중 점검, 안전자산 30% 유지 (IRP), 매수가 평균 확인</span></li>
          <li className="flex gap-2"><span className="text-sky-600 dark:text-sky-400 shrink-0">·</span><span>책 정신: 와병투자 (누워서 투자) — 매수/매도 빈도 ↓ 일수록 수익률 ↑</span></li>
        </ul>
      </section>

      {/* 5개 증권사 메뉴 위치 */}
      <section className="rounded-xl border border-border bg-card overflow-hidden">
        <header className="px-4 py-2.5 border-b border-border bg-muted/30">
          <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
            📱 국내 대표 증권사 5개 — 메뉴 위치
          </h2>
        </header>
        {/* Desktop: 4열 표 — md+ */}
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/20">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">증권사 · 앱</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">연금저축 / IRP</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">ISA</th>
                <th className="px-3 py-2 text-left font-medium text-muted-foreground">자동매수</th>
              </tr>
            </thead>
            <tbody>
              {BROKERS.map((b, i) => (
                <tr key={b.name} className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}>
                  <td className="px-3 py-2 align-top">
                    <div className="font-medium">{b.name}</div>
                    <div className="text-[10px] text-muted-foreground">{b.app}</div>
                  </td>
                  <td className="px-3 py-2 align-top">{b.pensionPath}</td>
                  <td className="px-3 py-2 align-top">{b.isaPath}</td>
                  <td className="px-3 py-2 align-top">{b.autoBuy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Mobile: 증권사별 카드 */}
        <ul className="md:hidden divide-y divide-border">
          {BROKERS.map((b) => (
            <li key={b.name} className="px-3 py-3 space-y-2">
              <div>
                <div className="text-xs font-semibold">{b.name}</div>
                <div className="text-[10px] text-muted-foreground">{b.app}</div>
              </div>
              <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 text-[11px]">
                <dt className="text-muted-foreground">연금/IRP</dt>
                <dd className="leading-relaxed">{b.pensionPath}</dd>
                <dt className="text-muted-foreground">ISA</dt>
                <dd className="leading-relaxed">{b.isaPath}</dd>
                <dt className="text-muted-foreground">자동매수</dt>
                <dd className="leading-relaxed">{b.autoBuy}</dd>
              </dl>
            </li>
          ))}
        </ul>

        <footer className="px-4 py-2 border-t border-border bg-muted/10 text-xs text-muted-foreground leading-relaxed">
          💡 메뉴 라벨은 앱 버전에 따라 달라질 수 있음 — 못 찾으면{" "}
          <strong>앱 검색창에 &quot;연금저축&quot; / &quot;IRP&quot; / &quot;ISA&quot; 검색</strong>이 가장 빠름.
          수수료(운용·자산관리·매매)는 증권사별 차이가 있으니 가입 전 비교 권장.
        </footer>
      </section>

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
