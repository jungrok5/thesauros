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
  Clock,
  Bed,
  Camera,
  RefreshCw,
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
    title: "종목 발견 — 검색 · 스크리너",
    body:
      "관심 종목 이름/코드를 알면 검색. 조건으로 찾고 싶으면 스크리너 — " +
      "추세 + 패턴 + 거래량 통과한 '책 정신 매수 후보' 만 노출.",
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

      {/* 운영 규칙 — 무엇이 언제 갱신되는지 */}
      <section className="rounded-xl border-2 border-zinc-500/30 bg-zinc-500/5 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Clock className="h-5 w-5 text-zinc-700 dark:text-zinc-300" />
          <h2 className="text-base font-semibold">
            데이터 갱신 일정 (2026-05-22 정리)
          </h2>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">
          책 정신상 매매 결정은 <strong>주봉 종가 후 1회</strong>. 이 룰에
          맞춰 cron 을 2 단으로 분리했습니다 — 매일 데이터 갱신과 주 1회
          결정 분석.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-muted-foreground">
              <tr className="text-left border-b border-border">
                <th className="py-2 pr-3 font-medium">시점</th>
                <th className="py-2 pr-3 font-medium">무엇이 갱신</th>
                <th className="py-2 font-medium">알림 발사?</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              <tr>
                <td className="py-2 pr-3 align-top">
                  <div className="font-medium">매일 17 KST</div>
                  <div className="text-muted-foreground">월~금</div>
                </td>
                <td className="py-2 pr-3 align-top space-y-0.5">
                  <div>· 종가 (bars) — 오늘 KR 종가 적재</div>
                  <div>· 거시 (macro_state) — FRED + 글로벌 지수</div>
                  <div>· 외인+기관 (investor_flow) — 책 5장 선행성 신호</div>
                  <div>· DART 새 공시 (watchlist 종목)</div>
                </td>
                <td className="py-2 align-top text-muted-foreground">
                  <div className="text-emerald-600 dark:text-emerald-400">🟡 이벤트 알림만</div>
                  <div className="mt-1">새 DART 공시 (자사주 매입 / 유상증자 / 5% 지분 등)</div>
                </td>
              </tr>
              <tr>
                <td className="py-2 pr-3 align-top">
                  <div className="font-medium">금요일 17 KST</div>
                  <div className="text-muted-foreground">매주 1회</div>
                </td>
                <td className="py-2 pr-3 align-top space-y-0.5">
                  <div>· <strong>전 종목 17 패턴 분석</strong> (scan_daily)</div>
                  <div>· 한 줄 평 + 매수 자격 + 매매플랜 갱신</div>
                  <div>· 알림 dedup 결정</div>
                </td>
                <td className="py-2 align-top text-muted-foreground">
                  <div className="text-emerald-600 dark:text-emerald-400">🟢 결정 알림</div>
                  <div className="mt-1">진입 / 추가매수 / 경고 / 청산 / 목표 / 손절</div>
                  <div className="mt-0.5 text-[10px]">월말 주에는 「📅 월말 주」 라벨 함께 표시 — 월봉 240MA / 포킹 점검 신호</div>
                </td>
              </tr>
              <tr>
                <td className="py-2 pr-3 align-top">
                  <div className="font-medium">토요일 11 KST</div>
                  <div className="text-muted-foreground">매주 1회</div>
                </td>
                <td className="py-2 pr-3 align-top space-y-0.5">
                  <div>· DART 재무 (fundamentals)</div>
                  <div>· DART 전체 공시 (disclosures)</div>
                  <div>· 어닝 캘린더 + 애널리스트 컨센서스 + 5% 보유</div>
                </td>
                <td className="py-2 align-top text-muted-foreground">없음 (데이터 적재만)</td>
              </tr>
              <tr>
                <td className="py-2 pr-3 align-top">
                  <div className="font-medium">일요일 10 KST</div>
                  <div className="text-muted-foreground">매주 1회</div>
                </td>
                <td className="py-2 pr-3 align-top space-y-0.5">
                  <div>· 종목 master (KRX 신규 상장 / 폐지 반영)</div>
                </td>
                <td className="py-2 align-top text-muted-foreground">없음</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="rounded-md border border-dashed border-border bg-muted/20 p-2 text-[11px] text-muted-foreground leading-relaxed">
          <strong className="text-foreground">읽는 법:</strong> 페이지에 표시되는 가격은
          <em> 직전 갱신 시점</em> 기준입니다. 페이지 상단의 freshness chip 으로 확인 가능.
          현재가는 별도 <a href="https://finance.naver.com/" target="_blank" rel="noopener noreferrer" className="underline">증권 앱</a> 에서 보세요 — 페이지 가격은 <strong>매매 결정용 (주봉 종가)</strong> 입니다.
        </div>
      </section>

      {/* 책 정신 5 규칙 */}
      <section className="rounded-xl border-2 border-emerald-500/30 bg-emerald-500/5 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <RefreshCw className="h-5 w-5 text-emerald-700 dark:text-emerald-300" />
          <h2 className="text-base font-semibold">책 정신 핵심 규칙 (요약)</h2>
        </div>
        <ol className="list-decimal list-inside space-y-2 text-sm leading-relaxed">
          <li>
            <strong>매매는 안 할수록 좋다</strong> — 코스톨라니: &ldquo;우량주
            샀으면 죄짓고 감옥에 가 있어라&rdquo;. 와병투자 (한달 누워있다
            말일 1회만 확인) 가 책의 이상.
          </li>
          <li>
            <strong>주봉 종가가 결정 단위</strong> — 매주 금요일 15:30 KST
            마감가 기준. 장중 변동에 흔들리지 말 것. 분석은 17 KST 이후
            (FDR 종가 publish 후) 페이지에서 확인.
          </li>
          <li>
            <strong>240MA 위 종목만 매수 대상</strong> — 그 아래는
            「죽은 차트」. 정배열 (위→아래: 5&gt;10&gt;20&gt;60&gt;120&gt;240) 만
            살아있는 종목. 역배열은 「사망유희」.
          </li>
          <li>
            <strong>거래량은 선행성</strong> — 가격 조작은 가능하나 거래량은
            못 숨김. 외인+기관 5일 동행 매수는 선행 신호 (책 5장).
          </li>
          <li>
            <strong>4등분선 25% 깨지면 손절</strong> — 직전 장대양봉 몸통
            25% 라인. 책 시그니처 매도 시그널. 페이지의 매매플랜이 자동 계산.
          </li>
        </ol>
      </section>

      {/* 알림 모드 — 와병투자 + 베타 */}
      <section className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Bed className="h-5 w-5 text-violet-700 dark:text-violet-300" />
          <h2 className="text-base font-semibold">알림 모드</h2>
        </div>
        <ul className="space-y-2 text-sm leading-relaxed">
          <li>
            <strong>🟢 결정 알림 (기본 ON)</strong> — 주봉 마감 후 enter /
            pyramid / warn / exit / target / stop.
          </li>
          <li>
            <strong>🟡 이벤트 알림 (기본 ON)</strong> — DART 새 공시 (자사주
            매입 / 유상증자 / 5% 지분 변동).
          </li>
          <li>
            <strong>🟠 가격 알림</strong> — watchlist 종목에 target/stop 등록
            시 자동.
          </li>
          <li>
            <strong>🛌 와병투자 모드</strong> (opt-in, 책의 이상적 모습) —
            ON 시 위 3 가지 모두 OFF + 금요일 종가 후 <strong>주 1회 통합 요약</strong>만
            받음. 손가락이 자꾸 가는 분께 권장.
            <Link href="/settings/alerts" className="ml-1 text-violet-700 dark:text-violet-300 underline">
              알림 설정에서 켜기
            </Link>
          </li>
        </ul>
      </section>

      {/* 페이지별 데이터 신선도 */}
      <section className="rounded-xl border border-border bg-card p-4 space-y-2">
        <div className="flex items-center gap-2">
          <Calendar className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-base font-semibold">페이지별 데이터 신선도</h2>
        </div>
        <ul className="text-sm space-y-1.5 text-muted-foreground">
          <li>· <strong className="text-foreground">/dashboard (거시)</strong> — 매일 갱신, KST 17 이후</li>
          <li>· <strong className="text-foreground">/stocks/[ticker]</strong> 한 줄 평 — <em>금요일</em> 갱신 (주봉 종가 기반)</li>
          <li>· <strong className="text-foreground">/stocks/[ticker]</strong> 가격/이평선 — 종가 (직전 17 KST)</li>
          <li>· <strong className="text-foreground">/stocks/[ticker]</strong> 외인+기관 / 공시 — 매일 갱신</li>
          <li>· <strong className="text-foreground">/screener</strong> 순위 — 금요일 갱신</li>
          <li>· <strong className="text-foreground">/watchlist</strong> — 실시간 (페이지 열 때 조회)</li>
        </ul>
        <div className="rounded-md border border-dashed border-border bg-muted/20 p-2 mt-2 text-[11px] text-muted-foreground leading-relaxed">
          모든 페이지 상단에 <strong>freshness chip</strong> 이 갱신 시점을 표시합니다. <em>최근 분석</em> 이후 며칠 지났는지 한눈에 확인.
        </div>
      </section>

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
          <li>
            <strong className="text-foreground">『미국 주식은 왜 자동 분석이 안 되나?』</strong>{" "}
            책 정신상 코스피·코스닥 종목 매매 + 미국은 글로벌 지수 (탑다운
            1단계) 로만 활용. Naver/Yahoo 가 cloud IP 차단으로 자동 수집도
            어려워 2026-05-22 부로 자동 분석 중단. KR 사이트가 만족스러운
            수준이 된 다음 미국 시장 지원 재검토.
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
