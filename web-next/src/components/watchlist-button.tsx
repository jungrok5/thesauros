"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  ticker: string;
  initiallyAdded?: boolean;
  initialCategory?: "observing" | "holding";
  /** 분석 결과의 action — AVOID/SELL/SELL_OR_SHORT 인 경우 신규 매수
   *  자격 X. "+ 보유" 클릭 시 confirm 한 번 띄움. 관심은 모니터링이
   *  자연스러우니 confirm 안 함. */
  action?: string | null;
}

const NO_BUY_ACTIONS = new Set(["AVOID", "SELL", "SELL_OR_SHORT"]);

export function WatchlistButton({
  ticker,
  initiallyAdded = false,
  initialCategory = "observing",
  action = null,
}: Props) {
  const [added, setAdded] = useState(initiallyAdded);
  const [category, setCategory] = useState<"observing" | "holding">(
    initialCategory,
  );
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function toggle(nextCategory: "observing" | "holding") {
    if (busy) return;
    // AVOID/SELL 종목을 "보유" 로 새로 추가하려는 경우 한 번 경고.
    // 이미 추가된 상태에서 카테고리만 바꾸는 경우는 OK (해제 가능).
    if (
      !added
      && nextCategory === "holding"
      && action
      && NO_BUY_ACTIONS.has(action)
    ) {
      const ok = window.confirm(
        "⚠️ 이 종목은 책 정신상 '신규 매수 자격 X' 판정입니다.\n\n" +
        "추세가 죽은 차트 (월봉 240MA 아래) 또는 청산 신호 상태.\n" +
        "그래도 보유 종목으로 추가하시겠습니까?\n\n" +
        "(관심 등록은 모니터링 목적으로 자유. 매수 자체는 본인 판단.)"
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      if (added && nextCategory === category) {
        // remove
        const r = await fetch(
          `/api/watchlist?ticker=${encodeURIComponent(ticker)}`,
          { method: "DELETE" },
        );
        if (!r.ok) throw new Error(String(r.status));
        setAdded(false);
      } else {
        // upsert
        const r = await fetch("/api/watchlist", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker, category: nextCategory }),
        });
        if (!r.ok) throw new Error(String(r.status));
        setAdded(true);
        setCategory(nextCategory);
      }
      router.refresh();
    } catch (e) {
      alert(`실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="inline-flex items-center gap-2" data-testid="watchlist-button">
      <button
        type="button"
        onClick={() => toggle("observing")}
        disabled={busy}
        data-testid="watchlist-observing"
        className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${
          added && category === "observing"
            ? "bg-foreground text-background border-foreground"
            : "bg-background border-input hover:bg-muted"
        }`}
      >
        {added && category === "observing" ? "✓ 관심 종목" : "+ 관심"}
      </button>
      <button
        type="button"
        onClick={() => toggle("holding")}
        disabled={busy}
        data-testid="watchlist-holding"
        className={`px-3 py-1.5 rounded-md text-sm font-medium border transition-colors ${
          added && category === "holding"
            ? "bg-emerald-600 text-white border-emerald-600"
            : "bg-background border-input hover:bg-muted"
        }`}
      >
        {added && category === "holding" ? "✓ 보유 중" : "+ 보유"}
      </button>
    </div>
  );
}
