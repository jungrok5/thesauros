import { TickerSearch } from "@/components/ticker-search";

export default function StockSearchPage() {
  return (
    <div className="space-y-8 max-w-4xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Stock Search</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          종목 코드를 입력하면 책의 전체 룰(추세 + 패턴 + 거래량 + 매매플랜)로
          분석합니다.
        </p>
      </header>

      <section className="rounded-xl border border-border bg-card p-5">
        <TickerSearch autoFocus />
      </section>

      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="text-sm font-medium mb-3">티커 입력 규칙</h2>
        <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
          <li>
            <span className="font-mono">AAPL</span>,{" "}
            <span className="font-mono">MSFT</span> — 미국 종목 (대소문자 무관)
          </li>
          <li>
            <span className="font-mono">005930.KS</span> — KOSPI 종목 (6자리 +
            .KS)
          </li>
          <li>
            <span className="font-mono">035420.KQ</span> — KOSDAQ 종목 (6자리 +
            .KQ)
          </li>
          <li>
            <span className="font-mono">005930</span> — 6자리만 입력하면 자동
            .KS 추가
          </li>
        </ul>
      </section>
    </div>
  );
}
