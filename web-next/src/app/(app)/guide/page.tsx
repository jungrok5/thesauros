/**
 * /guide — 직접 투자 전에 거쳐야 할 절세·연금 셋팅 5단계.
 *
 * 책 정신(추세추종) + 한국 세법(2026 기준)을 결합한 교과서 순서:
 *   1. 퇴직연금  DB vs DC + 안정형/공격형 운용
 *   2. 연금저축  (세액공제 600만원)
 *   3. IRP       (추가 300만원, 합산 900만원)
 *   4. ISA       3년 풍차돌리기 + 연금이전 꿀팁
 *   5. 직접투자  한국/미국 일반계좌 (이 사이트 핵심)
 *
 * 모든 수치는 2026 한국 세법 기준. 투자 결정은 본인 책임 — 가이드는
 * 절세 + 책 정신의 조합 정보 제공만 한다.
 */
import Link from "next/link";
import { ArrowLeft, Building2, Wallet, PiggyBank, Briefcase, TrendingUp, AlertTriangle, Lightbulb, ChevronRight } from "lucide-react";

export const dynamic = "force-static";

interface ProfileRow {
  label: string;
  /** 안정형 추천 */
  conservative: string;
  /** 공격형 추천 */
  aggressive: string;
}

interface Step {
  num: number;
  icon: typeof Building2;
  title: string;
  subtitle: string;
  why: string;
  /** 절세 + 한도 + 룰 */
  rules: Array<{ label: string; value: string }>;
  /** 안정형 vs 공격형 추천 종목 */
  profiles?: ProfileRow[];
  /** 핵심 꿀팁 */
  tips?: string[];
  /** 주의사항 */
  warnings?: string[];
}

const STEPS: Step[] = [
  {
    num: 1,
    icon: Building2,
    title: "퇴직연금 — DB vs DC 결정",
    subtitle: "회사 다닌다면 가장 큰 자산. 운용 방식부터 정해야 함.",
    why:
      "DB(확정급여)는 회사가 운용+보장, DC(확정기여)는 본인이 운용+책임. " +
      "임금 상승률이 시장 수익률보다 높다면 DB가 유리, 시장 수익률이 높다면 DC가 유리. " +
      '"DB → DC 무조건 전환"은 위험 — 본인 운용 자신 + 임금 정체기에만.',
    rules: [
      { label: "DC 전환", value: "한 번 DC → 다시 DB X (영구). 신중." },
      { label: "회사 적립금", value: "연봉의 1/12 이상 (DB·DC 동일)" },
      { label: "운용 한도 (DC)", value: "위험자산 70% / 안전자산 30% 의무" },
      { label: "수령 방법", value: "55세 이상 + 5년 이상 가입 → 연금 형태로 수령 (퇴직소득세 30% 감면)" },
    ],
    profiles: [
      {
        label: "DB vs DC",
        conservative: "DB 유지 — 회사 보장. 임금 상승률 좋으면 DC보다 유리할 수 있음.",
        aggressive: "DC 전환 + 적극 운용. 시장 수익률 > 임금 상승률 자신 있을 때만.",
      },
      {
        label: "위험자산 70%",
        conservative: "TDF 2045/2050 (자동 자산배분) — 시간 지나면서 안전자산 비중 자동 ↑",
        aggressive: "TIGER 미국S&P500 + TIGER 미국나스닥100 + (선택) 한국 K-반도체/AI",
      },
      {
        label: "안전자산 30% (의무)",
        conservative: "ACE 단기채권 + KODEX 종합채권액티브 (안전 최우선)",
        aggressive: "ACE 미국30년국채액티브 (듀레이션 활용) + KODEX 종합채권액티브 (국채+회사채 혼합 액티브 — 단순 단기채보다 효율 ↑)",
      },
    ],
    tips: [
      "퇴사 시 받은 퇴직금은 자동으로 IRP 계좌로 이전 (의무) — 연금으로 받으면 퇴직소득세 30% 감면.",
      "DC 운용 성과는 정기적으로 확인 — 회사가 디폴트로 안전자산 100%에 두면 인플레 손해.",
      "공격형이라도 안전자산 30% 채울 때 단기채권만 X — 국채혼합/액티브 채권은 금리 사이클과 신용 스프레드를 활용해 수익 추구 가능.",
    ],
    warnings: [
      "DB에서 DC로 전환하면 그때까지 DB 적립금은 환산되어 DC로 이동 — 환산금이 정확한지 확인.",
      "회사 폐업 시 DB는 일부만 보장 (DC는 본인 계좌라 무관).",
    ],
  },
  {
    num: 2,
    icon: PiggyBank,
    title: "연금저축 — 세액공제 600만원 풀 사용",
    subtitle: "직접투자 전에 무조건 세팅. 매년 약 99만원 환급.",
    why:
      "연 600만원 납입 시 총급여 5,500만원 이하면 16.5%, 초과면 13.2% 세액공제. " +
      "운용 자율 (펀드/ETF/리츠), 인출 제약은 강하지만 절세 효과가 압도적. " +
      "사실상 \"매년 99만원 정부가 주는 무료 수익\".",
    rules: [
      { label: "세액공제 한도", value: "연 600만원 (납입 시 13.2~16.5% 환급)" },
      { label: "총 납입 한도", value: "연 1,800만원 (초과분도 운용 가능, 세액공제는 600까지)" },
      { label: "위험자산 한도", value: "100% 가능 (IRP보다 자유)" },
      { label: "수령", value: "55세 이상 + 5년 이상 + 연금 형태 → 연금소득세 3.3~5.5%" },
      { label: "중도해지", value: "기타소득세 16.5% + 세액공제 반환 (사실상 손해)" },
    ],
    profiles: [
      {
        label: "운용 종목 (절세 + 책 정신)",
        conservative: "TIGER 미국배당다우존스 (SCHD 한국판) + KOSEF 국고채10년 + ACE 단기채권",
        aggressive: "TIGER 미국S&P500 + TIGER 미국나스닥100 + KODEX K-반도체/AI",
      },
    ],
    tips: [
      "월 50만원 자동이체 = 연 600만원 완납 — 작은 단위로 분산 매수 (책 정신: 분할 진입).",
      "연금저축은 ETF 매매 시 매도차익 비과세 (일반계좌는 22% 양도세). 미국 ETF 운용에 최적.",
      "배당금도 연금저축 안에 있으면 인출 전까지 비과세 — 복리 효과 극대화.",
    ],
    warnings: [
      "55세 이전 중도 해지하면 절세분 + 운용수익에 16.5% 기타소득세 — 사실상 \"꺼낼 수 없는 돈\"이라 생각하고 운용.",
      "1년 600만원 초과 납입은 가능하지만 추가 세액공제는 X.",
    ],
  },
  {
    num: 3,
    icon: Briefcase,
    title: "IRP — 추가 300만원으로 합산 900만원 세액공제",
    subtitle: "연금저축 다음 자동 set. 추가 약 49만원 환급.",
    why:
      "연금저축 600만원 + IRP 추가 300만원 = 합산 연 900만원까지 세액공제. " +
      "두 계좌를 합쳐 운영. IRP는 위험자산 70% 제한이 있지만 안전자산 30%를 \"채권 ETF로 채우면 사실상 70% 주식\"이라 큰 제약 X.",
    rules: [
      { label: "세액공제 한도", value: "연금저축 + IRP 합산 연 900만원 (= IRP 단독 700만원도 가능)" },
      { label: "위험자산 한도", value: "위험자산(주식·주식ETF) 70% / 안전자산 30% 의무" },
      { label: "수령", value: "55세 이상 + 연금 형태 → 연금소득세 3.3~5.5%" },
      { label: "퇴직금 합산", value: "퇴직금을 IRP로 받으면 같은 계좌에서 운용 — 퇴직소득세 30% 감면" },
    ],
    profiles: [
      {
        label: "위험자산 70%",
        conservative: "TDF 2045/2050 — 자동 자산배분 (시간 지나면 안전자산 비중 자동 ↑)",
        aggressive: "TIGER 미국S&P500 + TIGER 미국나스닥100 (성장 위주)",
      },
      {
        label: "안전자산 30% (의무)",
        conservative: "ACE 단기채권 + KCD금리액티브 (안전 최우선)",
        aggressive: "ACE 미국30년국채액티브 (금리 인하 사이클 활용) + KODEX 종합채권액티브 (국채+회사채 혼합) — 단순 단기채권보다 듀레이션 + 신용 스프레드로 수익 추구",
      },
    ],
    tips: [
      "IRP는 연금저축에 없는 \"퇴직금 보관\" 기능 — 회사 퇴사 시 IRP로 자동 입금. 그대로 운용 가능.",
      "공격형 30% 안전자산을 \"국채혼합/액티브 채권\"으로 채우면 단순 단기채보다 1~3%p 추가 수익 가능. 책 정신: 금리 사이클 (인하 → 채권 가격 ↑) 활용.",
      "ETF는 연금저축 우선 (위험자산 100% 가능), IRP는 채권·TDF·30% 안전자산 위주로 — 두 계좌 합쳐 효율 극대.",
      "총급여 5,500만원 이하라면 900만원 풀 납입 → 연 약 148만원 환급 (월 12만원 부수입).",
    ],
    warnings: [
      "IRP에서 ETF 매수 시 매수 수수료 + 운용보수 — 일반 증권사보다 약간 비쌈. 미래에셋·NH투자증권 등 비교.",
      "55세 이전 중도해지 시 16.5% 기타소득세 + 세액공제 반환.",
    ],
  },
  {
    num: 4,
    icon: Wallet,
    title: "ISA — 비과세 200만원 + 연금 이전 꿀팁",
    subtitle: "연 2,000만원 한도. 3년 의무 가입 후 \"풍차돌리기\".",
    why:
      "ISA 안에서 발생한 이익 200만원까지 비과세 (서민·농어민 400만원). " +
      "초과분은 분리과세 9.9% — 일반계좌(15.4%)보다 낮음. " +
      "최대 1억원까지 (연 한도 2,000만원, 미사용분 이월 가능).",
    rules: [
      { label: "납입 한도", value: "연 2,000만원, 총 1억원 한도 (미사용분 다음 해 이월)" },
      { label: "비과세", value: "이익 200만원까지 (서민·농어민 400만원)" },
      { label: "분리과세", value: "초과분 9.9% (일반계좌 15.4% 대비 5.5%p 절감)" },
      { label: "의무 가입", value: "3년 (만기 후 해지/연장 자유)" },
      { label: "운용 가능 자산", value: "ETF, 주식, ELS, RP, 예적금 등" },
    ],
    profiles: [
      {
        label: "운용 종목",
        conservative: "예금형 + 배당 ETF (TIGER 미국배당다우존스) + 채권 ETF",
        aggressive: "한국 성장 ETF + 미국 S&P500/QQQ ETF + 일부 개별주",
      },
    ],
    tips: [
      "★★★ 꿀팁: ISA 만기 → 연금저축으로 이전 시 추가 300만원 세액공제 (1회성, 약 40만원 환급).",
      "3년 풍차돌리기 = 매년 ISA를 가입해 3년 후 만기 도래 → 비과세 받고 새 ISA로 갈아타기 (계속 굴림).",
      "ISA는 미국 주식 직접 매매 불가 — 미국 노출은 미국 ETF (한국 상장)로.",
      "신탁형 / 일임형 / 중개형 중 \"중개형\"이 본인이 직접 운용 — 책 정신에 맞음.",
    ],
    warnings: [
      "ISA 안에서 발생한 손실은 다른 계좌 손익과 통산 X — 손실 위험 큰 종목은 일반계좌가 나음.",
      "3년 의무 가입 중 해지 시 그동안 받은 비과세 / 분리과세 혜택 반환.",
    ],
  },
  {
    num: 5,
    icon: TrendingUp,
    title: "직접투자 — 한국 + 미국 + 책 정신",
    subtitle: "위 4단계 완료 후 잉여 자금으로. 이 사이트의 본 영역.",
    why:
      "연금/ISA 세제 혜택을 다 채운 후의 \"여유 자금\" 영역. " +
      "이 사이트는 책 (캔들차트 추세추종) + DART/SEC 펀더멘털을 기반으로 종목별 분석 제공. " +
      "한국 = 양도소득세 X (대주주 제외), 미국 = 22% (250만원 공제 후) + 환율 리스크.",
    rules: [
      { label: "한국 종목", value: "양도소득세 X (대주주 제외), 배당세 15.4%" },
      { label: "미국 종목", value: "양도소득세 22% (연 250만원 공제 후), 배당세 15%" },
      { label: "환율 리스크", value: "USD 환산 시 변동 — 환차익 5천만원 초과 시 신고" },
      { label: "거래시간", value: "한국 09:00-15:30 KST, 미국 23:30-06:00 (서머타임 22:30-05:00)" },
    ],
    profiles: [
      {
        label: "포트폴리오 비중 (참고)",
        conservative: "연금/ISA 80% + 직접투자 20% (분산)",
        aggressive: "연금/ISA 50% + 직접투자 50% (책 정신 매매 학습)",
      },
    ],
    tips: [
      "이 사이트의 정리표 + BookVerdict 사용 — 매번 종목 검색 시 책 정신 분석 자동.",
      "관심 종목 추가 시 자동 분석 + 텔레그램 알림 — 매수/청산 시그널 놓치지 X.",
      "책 정신: 종목보다 타이밍, 정배열 + 240MA 위 + 8주 트레일링 +50% 안 + 캔들 신호 확인 후 진입.",
    ],
    warnings: [
      "선물·옵션·레버리지 X — 책의 원칙. 추세추종은 \"주봉 종가매매 + 분할 진입\".",
      "신용·미수 거래 X — 자본 보전이 책의 1순위.",
      "본 가이드는 정보 제공 목적, 투자 결정은 본인 책임.",
    ],
  },
];

// Master cheat-sheet rows for the top summary table.
interface CheatRow {
  step: string;
  taxBreak: string;
  withdrawal: string;
  notes: string;
}

const CHEAT_ROWS: CheatRow[] = [
  {
    step: "1. 퇴직연금 DC",
    taxBreak: "퇴직소득세 30% 감면 (연금 수령 시)",
    withdrawal: "55세+, 연금 형태",
    notes: "위험자산 70% / 안전자산 30%",
  },
  {
    step: "2. 연금저축",
    taxBreak: "연 600만원 × 13.2~16.5% = 약 99만원/년",
    withdrawal: "55세+, 5년+, 연금 3.3~5.5%",
    notes: "위험자산 100% 가능, ETF 매매 비과세",
  },
  {
    step: "3. IRP",
    taxBreak: "추가 300만원 × 13.2~16.5% = 약 49만원/년",
    withdrawal: "55세+, 연금 형태",
    notes: "위험자산 70% (안전자산 30% 의무)",
  },
  {
    step: "4. ISA",
    taxBreak: "이익 200만원 비과세, 초과 9.9%",
    withdrawal: "3년 의무 가입 후 자유",
    notes: "만기 → 연금저축 이전 시 +300만원 세액공제",
  },
  {
    step: "5. 직접투자",
    taxBreak: "한국 X (대주주 제외) / 미국 22%",
    withdrawal: "언제든",
    notes: "여유 자금만. 책 정신 분석은 이 사이트가 자동",
  },
];

export default function GuidePage() {
  return (
    <div className="space-y-8 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          📚 직접 투자 전에 — 절세 + 연금 셋팅 가이드
        </h1>
        <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
          교과서적으로 당연한 5단계 순서. 직접 투자(이 사이트 본 영역)는 마지막 단계. 그 전에 거쳐야 할 절세
          + 연금 셋팅을 안 하면 매년 정부가 주는 약 <strong className="text-foreground">148만원 환급</strong>을 놓치고 시작.
          한국 2026년 세법 기준.
        </p>
        <p className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/5 px-2 py-1 text-xs text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-3.5 w-3.5" />
          본 가이드는 정보 제공 목적입니다. 투자 결정은 본인 책임.
        </p>
      </header>

      {/* Cheat-sheet at the top */}
      <section className="rounded-xl border border-border bg-card overflow-hidden">
        <header className="px-4 py-2.5 border-b border-border bg-muted/30">
          <h2 className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
            🗺️ 한눈에 — 5단계 절세 지도
          </h2>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/20">
                <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">단계</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">절세 효과</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">인출 조건</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">비고</th>
              </tr>
            </thead>
            <tbody>
              {CHEAT_ROWS.map((row, i) => (
                <tr
                  key={row.step}
                  className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-muted/10" : ""}`}
                >
                  <td className="px-4 py-2 align-top font-medium">{row.step}</td>
                  <td className="px-4 py-2 align-top">{row.taxBreak}</td>
                  <td className="px-4 py-2 align-top text-muted-foreground">{row.withdrawal}</td>
                  <td className="px-4 py-2 align-top text-muted-foreground">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <footer className="px-4 py-2 border-t border-border bg-muted/10 text-xs text-muted-foreground">
          연금저축 600 + IRP 300 = 합산 900만원 풀 납입 시 매년 약 <strong className="text-foreground">148만원</strong> 환급.
          ISA 만기 + 연금 이전까지 활용하면 추가 <strong className="text-foreground">40만원</strong>.
        </footer>
      </section>

      {/* 5 steps */}
      {STEPS.map((step) => {
        const Icon = step.icon;
        return (
          <section
            key={step.num}
            className="rounded-xl border border-border bg-card p-6 space-y-4"
            id={`step-${step.num}`}
          >
            <header className="flex items-start gap-3 pb-3 border-b border-border">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border-2 border-border bg-background">
                <Icon className="h-5 w-5" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
                  단계 {step.num} / 5
                </div>
                <h2 className="text-lg font-semibold tracking-tight">{step.title}</h2>
                <p className="text-xs text-muted-foreground mt-0.5">{step.subtitle}</p>
              </div>
            </header>

            <p className="text-sm leading-relaxed">{step.why}</p>

            {/* Rules table */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              {step.rules.map((r) => (
                <div
                  key={r.label}
                  className="flex items-start gap-2 rounded-md border border-border bg-muted/10 px-3 py-2"
                >
                  <span className="font-medium text-muted-foreground shrink-0 min-w-[6rem]">
                    {r.label}
                  </span>
                  <span>{r.value}</span>
                </div>
              ))}
            </div>

            {/* Profile rows (안정형 vs 공격형) */}
            {step.profiles && step.profiles.length > 0 && (
              <div className="rounded-lg border border-border overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border bg-muted/30">
                      <th className="px-3 py-2 text-left text-[11px] font-medium text-muted-foreground"></th>
                      <th className="px-3 py-2 text-left text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
                        🛡️ 안정형
                      </th>
                      <th className="px-3 py-2 text-left text-[11px] font-medium text-amber-700 dark:text-amber-300">
                        ⚡ 공격형
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {step.profiles.map((p) => (
                      <tr key={p.label} className="border-b border-border last:border-b-0">
                        <td className="px-3 py-2 align-top text-xs font-medium text-muted-foreground">
                          {p.label}
                        </td>
                        <td className="px-3 py-2 align-top text-xs">{p.conservative}</td>
                        <td className="px-3 py-2 align-top text-xs">{p.aggressive}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Tips */}
            {step.tips && step.tips.length > 0 && (
              <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-3 space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-sky-700 dark:text-sky-300">
                  <Lightbulb className="h-3.5 w-3.5" /> 꿀팁
                </div>
                <ul className="text-xs space-y-1 text-foreground/85">
                  {step.tips.map((t, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-sky-600 dark:text-sky-400 shrink-0">·</span>
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Warnings */}
            {step.warnings && step.warnings.length > 0 && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 space-y-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 dark:text-rose-300">
                  <AlertTriangle className="h-3.5 w-3.5" /> 주의
                </div>
                <ul className="text-xs space-y-1 text-foreground/85">
                  {step.warnings.map((w, i) => (
                    <li key={i} className="flex gap-2">
                      <span className="text-rose-600 dark:text-rose-400 shrink-0">·</span>
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        );
      })}

      {/* Final CTA */}
      <section className="rounded-xl border-2 border-emerald-500/40 bg-emerald-500/5 p-6 space-y-3">
        <div className="text-[10px] uppercase tracking-widest text-emerald-700 dark:text-emerald-300">
          5단계 모두 셋팅 완료했다면
        </div>
        <h2 className="text-xl font-semibold tracking-tight">
          이제 직접 투자 — 책 정신으로 한 종목씩 분석하세요.
        </h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          이 사이트는 캔들차트 추세추종 책 (성승현, 2026)의 모든 룰을 자동화한 도구입니다. 종목 검색
          → 정리표 한 곳에서 추세 / 8주 상승률 / 캔들 / 거래량 / 패턴 / 4등분선 / RSI·MACD / 손절선
          / 외인+기관 한눈에. 매수/청산 신호는 텔레그램 알림으로.
        </p>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/stocks"
            className="inline-flex items-center gap-1.5 rounded-md border-2 border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm font-medium text-emerald-700 dark:text-emerald-300 hover:opacity-90"
          >
            종목 검색 시작
            <ChevronRight className="h-4 w-4" />
          </Link>
          <Link
            href="/glossary"
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
          >
            용어집 보기
            <ChevronRight className="h-4 w-4" />
          </Link>
        </div>
      </section>
    </div>
  );
}
