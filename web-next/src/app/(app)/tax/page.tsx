/**
 * /tax — 세금 시뮬레이터 + 연말 절세 매도 시기 추천기.
 *
 * 클라이언트 컴포넌트들에 모두 계산 로직 위임 (lib/tax-calc.ts). 페이지는
 * shell + 안내 톤만 책임.
 */
import Link from "next/link";
import { ArrowLeft, Calculator } from "lucide-react";
import { TaxSimulators } from "./simulators-client";

// NB: NOT `force-static` even though the page has no auth-dependent
// data — the (app) layout's auth() check would bake a redirect into
// the static HTML and F5 would bounce logged-in users to /login.
// See src/__tests__/auth-protected-pages.test.ts for the guard.

export default function TaxPage() {
  return (
    <div className="space-y-6 max-w-3xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Calculator className="h-6 w-6" /> 세금 시뮬레이터
        </h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          한국 2026 세법 기준. 미국 주식 양도세 + 연말 절세 매도 시기 +
          ISA 만기 → 연금저축 이전 환급 계산. 모든 계산은 본인 입력 기반,
          개인 정보 저장 X (클라이언트 단 계산).
        </p>
      </header>

      <section className="rounded-xl border-2 border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-amber-700 dark:text-amber-300">
          💡 한국 주식 세금 핵심 (2026)
        </div>
        <ul className="text-xs space-y-1 leading-relaxed">
          <li className="flex gap-2"><span className="text-amber-700 dark:text-amber-300">·</span><span><strong>한국 개별주</strong>: 대주주 아니면 양도세 0%. 배당세 15.4%만.</span></li>
          <li className="flex gap-2"><span className="text-amber-700 dark:text-amber-300">·</span><span><strong>미국 (해외) 주식</strong>: 양도세 22% (지방세 포함), 단 <strong>연 250 만 원 기본공제</strong>. 250 만까지는 무세금.</span></li>
          <li className="flex gap-2"><span className="text-amber-700 dark:text-amber-300">·</span><span><strong>손익 통산</strong>: 같은 해 손실은 차익에서 차감. 12 월 셋째 주까지 매도 결제일 포함되어야 올해 정산.</span></li>
          <li className="flex gap-2"><span className="text-amber-700 dark:text-amber-300">·</span><span><strong>ISA 만기 → 연금저축 이전</strong>: 이전금의 10% (최대 300 만) 의 13.2~16.5% 가 추가 세액공제 (1 회성).</span></li>
        </ul>
      </section>

      <TaxSimulators />
    </div>
  );
}
