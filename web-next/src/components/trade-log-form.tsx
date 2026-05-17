"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export function TradeLogForm() {
  const router = useRouter();
  const today = new Date().toISOString().slice(0, 10);
  const [ticker, setTicker] = useState("");
  const [action, setAction] = useState<"buy" | "sell">("buy");
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("");
  const [tradeDate, setTradeDate] = useState(today);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch("/api/trade-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: ticker.toUpperCase(),
          action,
          price: Number(price),
          quantity: quantity ? Number(quantity) : null,
          trade_date: tradeDate,
          reason: reason || null,
        }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.error ?? String(r.status));
      }
      setTicker(""); setPrice(""); setQuantity(""); setReason("");
      router.refresh();
    } catch (e) {
      alert(`기록 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-lg border border-border bg-card p-4 grid grid-cols-1 sm:grid-cols-7 gap-2"
    >
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="티커"
        required
        className="sm:col-span-1 px-2 py-1.5 rounded border border-input bg-background text-sm font-mono"
      />
      <select
        value={action}
        onChange={(e) => setAction(e.target.value as "buy" | "sell")}
        className="sm:col-span-1 px-2 py-1.5 rounded border border-input bg-background text-sm"
      >
        <option value="buy">매수</option>
        <option value="sell">매도</option>
      </select>
      <input
        type="number"
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        placeholder="가격"
        required
        step="0.01"
        className="sm:col-span-1 px-2 py-1.5 rounded border border-input bg-background text-sm font-mono"
      />
      <input
        type="number"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        placeholder="수량"
        className="sm:col-span-1 px-2 py-1.5 rounded border border-input bg-background text-sm font-mono"
      />
      <input
        type="date"
        value={tradeDate}
        onChange={(e) => setTradeDate(e.target.value)}
        required
        className="sm:col-span-1 px-2 py-1.5 rounded border border-input bg-background text-sm"
      />
      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="이유 (예: 240MA 돌파)"
        maxLength={300}
        className="sm:col-span-1 px-2 py-1.5 rounded border border-input bg-background text-sm"
      />
      <button
        type="submit"
        disabled={busy}
        className="sm:col-span-1 px-3 py-1.5 rounded bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-50"
      >
        {busy ? "..." : "추가"}
      </button>
    </form>
  );
}
