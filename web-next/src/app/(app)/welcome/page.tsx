/**
 * /welcome — 첫 사용자 온보딩 5 step 가이드.
 *
 * 책 정신 추세추종 매매 도구를 처음 쓰는 사용자가 어디서 시작 → 어떻게
 * 매매 결정 → 어떻게 모니터링 하는지 4-5 카드로 안내. 사이드바 최상단
 * "📖 시작하기" 에서 진입.
 *
 * 책 정신 용어를 카드 본문에서 최소화 — 초보자 진입 장벽 완화. 더
 * 깊은 설명은 각 step 의 페이지 안 HelpTip / 가이드 박스에서.
 */
import Link from "next/link";
import {
  ArrowLeft,
  ArrowRight,
  Compass,
  Search,
  TrendingUp,
  Star,
  AlertTriangle,
  Calendar,
} from "lucide-react";

export const dynamic = "force-dynamic";

const STEPS: Array<{
  num: string;
  icon: typeof Compass;
  title: string;
  body: string;
  cta: { href: string; label: string };
}> = [
  {
    num: "1",
    icon: Compass,
    title: "시장 분위기부터 확인",
    body:
      "개별 종목 사기 전에 거시 (Macro) 페이지에서 시장이 강세인지 약세인지 본다. " +
      "큰 그림이 약하면 어떤 종목도 진입 자제 — 이게 책 정신 첫 룰.",
    cta: { href: "/dashboard", label: "거시 보러 가기" },
  },
  {
    num: "2",
    icon: Search,
    title: "종목 발견 — 검색 · 스크리너 · 테마",
    body:
      "관심 종목 이름/코드를 알면 검색. 조건으로 찾고 싶으면 스크리너 (PER < 15 + 책 점수 등). " +
      "테마별 분류는 테마 페이지에서.",
    cta: { href: "/stocks", label: "종목 검색 시작" },
  },
  {
    num: "3",
    icon: TrendingUp,
    title: "종목 페이지 — 한 줄 평이 결론",
    body:
      "어느 경로로 들어왔든 종목 상세 페이지 최상단에 🟢🟡🔴 색상으로 매수/관망/회피 결론. " +
      "본문 + 매매플랜 (진입 · 손절 · 목표) + 시장 흐름 + 펀더가 그 결론의 근거. " +
      "차트는 시각 검증용.",
    cta: { href: "/stocks/005930.KS", label: "예시: 삼성전자" },
  },
  {
    num: "4",
    icon: Star,
    title: "관심 종목 추가 → 매주 자동 알림",
    body:
      "매수했거나 관심 있는 종목은 종목 페이지에서 '관심' 또는 '보유'로 추가. " +
      "매주 금요일 17 KST 자동 분석 — EXIT 신호 (청산 자리) 발생 시 텔레그램으로 즉시 알림. " +
      "놓치지 않도록.",
    cta: { href: "/watchlist", label: "내 관심 종목" },
  },
  {
    num: "5",
    icon: Calendar,
    title: "결정 시점은 매주 금요일 종가",
    body:
      "책 정신은 주봉 종가매매 — 장중 wick (꼬리) 무시, 금요일 15:30 KST 마감가 기준. " +
      "그 외 평일에는 모니터링만, 매수/매도 결정은 금요일에. " +
      "체크 list 와 절세 가이드는 ↓.",
    cta: { href: "/guide", label: "절세·연금 가이드" },
  },
];

export default function WelcomePage() {
  return (
    <div className="space-y-6 max-w-4xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">
          👋 시작하기
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          책 정신 (캔들차트 추세추종) 으로 종목 선택 + 매매 결정하는 5 step 가이드.
          중간 어디든 막히면 사이드바 아이콘으로 돌아오세요.
        </p>
      </header>

      {/* 핵심 원칙 안내 — 책 정신 1줄 */}
      <section className="rounded-xl border-2 border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
        <div className="flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-2 text-sm leading-relaxed">
            <div className="font-semibold text-amber-900 dark:text-amber-100">
              책 정신 핵심 — 매매는 안 할수록 좋다
            </div>
            <p>
              이 도구는 『매수해야 할 종목』을 추천하지 않습니다. <strong>책 정신상 매수해도
              OK 인 자리</strong> 를 보여줄 뿐 — 결정은 본인이. 손실 책임도 본인.
              5 step 다 따라간 후에도 본인이 차트를 직접 검증한 자리에서만 진입하세요.
            </p>
          </div>
        </div>
      </section>

      {/* 5 step 카드 */}
      <ol className="space-y-3">
        {STEPS.map((s) => (
          <li key={s.num}>
            <article className="rounded-xl border border-border bg-card p-4">
              <div className="flex items-start gap-3">
                <div className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-foreground/5 text-base font-bold">
                  {s.num}
                </div>
                <div className="flex-1 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <s.icon className="h-4 w-4 text-muted-foreground" />
                    <h2 className="text-base font-semibold tracking-tight">{s.title}</h2>
                  </div>
                  <p className="text-sm leading-relaxed text-muted-foreground">{s.body}</p>
                  <Link
                    href={s.cta.href}
                    className="inline-flex items-center gap-1 text-sm font-medium text-foreground hover:underline mt-1"
                  >
                    {s.cta.label} <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </div>
            </article>
          </li>
        ))}
      </ol>

      {/* 추가 안내 */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-2 text-sm leading-relaxed">
        <h2 className="font-semibold">📌 자주 받는 질문</h2>
        <ul className="space-y-2 text-muted-foreground">
          <li>
            <strong className="text-foreground">『매수 자격 종목 = 무조건 사라?』</strong>{" "}
            아닙니다. 한 줄 평이 🟢 강매수여도 본인 차트 + 펀더 검증 통과 시에만.
            동률 1.00 점 종목 안에서도 거래량 폭증 / 4등분선 safe75 / catalyst 직후 같은
            세부 차이가 큽니다 — 스크리너 chip 가이드 펼쳐서 확인.
          </li>
          <li>
            <strong className="text-foreground">『손절 가격에 닿으면 즉시 매도?』</strong>{" "}
            아닙니다. <strong>주봉 금요일 종가</strong>가 손절가 아래로 마감했을 때만.
            장중에 잠깐 깨졌다 위로 마감하면 보유 유지.
          </li>
          <li>
            <strong className="text-foreground">『목표가 도달 시 무조건 익절?』</strong>{" "}
            아닙니다. 추세가 살아있으면 보유 — 10MA 이탈 시점이 진짜 청산 시점.
            목표가는 『일부 익절 검토 라인』 정도.
          </li>
          <li>
            <strong className="text-foreground">『AVOID/회피 종목도 관심에 넣을 수 있나?』</strong>{" "}
            가능하지만 책 정신상 신규 매수 자격 X. 매수 시도 시 한 번 경고.
            모니터링 목적이라면 OK.
          </li>
        </ul>
      </section>

      <div className="flex items-center justify-between text-xs text-muted-foreground pt-2">
        <span>위 5 step 다 익숙해지면 이 페이지는 더 안 보셔도 됩니다.</span>
        <Link href="/dashboard" className="hover:text-foreground">
          대시보드로 →
        </Link>
      </div>
    </div>
  );
}
