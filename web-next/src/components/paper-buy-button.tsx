"use client";

/**
 * 📒 가상 매수 버튼 + 모달.
 *
 * Stock detail page renders this next to the BookVerdict so users can
 * "forward-test" — paper-buy at the price the page is showing, with
 * the same stop/target the verdict surfaced. Screener rows render the
 * compact icon variant.
 *
 * The button reads entry_plan from the AnalysisResult prop the parent
 * server component already has — no extra round-trip to compute it.
 */
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

interface Props {
  ticker: string;
  /** Most recent close — the price the user will "pay" if they buy now. */
  entryPrice: number;
  /** Optional book-spirit stop_loss / target snapshot from entry_plan. */
  stopLoss?: number | null;
  target?: number | null;
  /** Compact icon mode for tight rows (스크리너). */
  compact?: boolean;
}

const PRESETS = [
  { label: "100만", value: 1_000_000 },
  { label: "500만", value: 5_000_000 },
  { label: "1천만", value: 10_000_000 },
  { label: "5천만", value: 50_000_000 },
];

export function PaperBuyButton({
  ticker, entryPrice, stopLoss, target, compact,
}: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState<number>(1_000_000);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setErr(null);
    try {
      const res = await fetch("/api/paper", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          ticker,
          amount_krw: amount,
          entry_price: entryPrice,
          stop_loss: stopLoss ?? null,
          target: target ?? null,
          notes: notes || null,
        }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setErr(j.error ?? `매수 실패 (${res.status})`);
        return;
      }
      setOpen(false);
      router.refresh();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSubmitting(false);
    }
  }, [ticker, amount, entryPrice, stopLoss, target, notes, router]);

  if (compact) {
    return (
      <>
        <button
          type="button"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true); }}
          title="가상 매수 (paper trade)"
          className="inline-flex items-center text-xs px-1.5 py-0.5 rounded
                     border border-border bg-card hover:bg-muted transition-colors"
        >
          📒+
        </button>
        {open && (
          <Modal
            ticker={ticker} entryPrice={entryPrice}
            stopLoss={stopLoss} target={target}
            amount={amount} setAmount={setAmount}
            notes={notes} setNotes={setNotes}
            err={err} submitting={submitting}
            onSubmit={submit} onClose={() => setOpen(false)}
          />
        )}
      </>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5
                   rounded-md border border-border bg-card hover:bg-muted
                   transition-colors"
      >
        📒 가상 매수
      </button>
      {open && (
        <Modal
          ticker={ticker} entryPrice={entryPrice}
          stopLoss={stopLoss} target={target}
          amount={amount} setAmount={setAmount}
          notes={notes} setNotes={setNotes}
          err={err} submitting={submitting}
          onSubmit={submit} onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}


interface ModalProps {
  ticker: string;
  entryPrice: number;
  stopLoss?: number | null;
  target?: number | null;
  amount: number;
  setAmount: (n: number) => void;
  notes: string;
  setNotes: (s: string) => void;
  err: string | null;
  submitting: boolean;
  onSubmit: () => void;
  onClose: () => void;
}

function Modal({
  ticker, entryPrice, stopLoss, target,
  amount, setAmount, notes, setNotes,
  err, submitting, onSubmit, onClose,
}: ModalProps) {
  const shares = entryPrice > 0 ? amount / entryPrice : 0;
  const stopPct = stopLoss && stopLoss > 0
    ? ((stopLoss / entryPrice) - 1) * 100
    : null;
  const targetPct = target && target > 0
    ? ((target / entryPrice) - 1) * 100
    : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center
                 bg-background/80 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-border
                   bg-card p-5 shadow-lg space-y-4"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="가상 매수 모달"
      >
        <header>
          <h2 className="text-lg font-semibold">
            📒 가상 매수 — <span className="font-mono">{ticker}</span>
          </h2>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            실제 매수가 아닌 forward-test 입니다. 손절선/목표는 분석 시점
            BookVerdict 의 값을 자동 사용합니다.
          </p>
        </header>

        <div className="rounded-md bg-muted/40 border border-border p-3 text-xs space-y-1">
          <div className="flex justify-between">
            <span className="text-muted-foreground">진입가 (현재 종가):</span>
            <span className="font-mono">{fmt(entryPrice)}원</span>
          </div>
          {stopLoss != null && stopPct != null && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">손절선:</span>
              <span className="font-mono text-rose-600 dark:text-rose-400">
                {fmt(stopLoss)}원 ({stopPct.toFixed(1)}%)
              </span>
            </div>
          )}
          {target != null && targetPct != null && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">목표가:</span>
              <span className="font-mono text-emerald-600 dark:text-emerald-400">
                {fmt(target)}원 (+{targetPct.toFixed(1)}%)
              </span>
            </div>
          )}
        </div>

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">
            매수 금액 (원)
          </label>
          <div className="flex gap-1.5 flex-wrap">
            {PRESETS.map((p) => (
              <button key={p.value}
                type="button"
                onClick={() => setAmount(p.value)}
                className={
                  "text-xs px-2 py-1 rounded-md border transition-colors " +
                  (amount === p.value
                    ? "border-foreground/40 bg-foreground/10"
                    : "border-border bg-card hover:bg-muted")
                }
              >
                {p.label}
              </button>
            ))}
          </div>
          <input
            type="number"
            min={1}
            step={10000}
            value={amount}
            onChange={(e) => setAmount(Math.max(0, Number(e.target.value)))}
            className="w-full rounded-md border border-border bg-background
                       px-3 py-2 text-sm font-mono"
          />
          <div className="text-xs text-muted-foreground">
            ≈ {shares.toFixed(2)}주 매수 (소수점 단위로 시뮬레이션)
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            메모 (선택)
          </label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="ex. 1위라서 / 책 정신 학습용"
            className="w-full rounded-md border border-border bg-background
                       px-3 py-2 text-sm"
          />
        </div>

        {err && (
          <div className="rounded-md border border-rose-500/40 bg-rose-500/5
                          px-3 py-2 text-xs text-rose-700 dark:text-rose-300">
            {err}
          </div>
        )}

        <footer className="flex justify-end gap-2 pt-2 border-t border-border">
          <button type="button" onClick={onClose} disabled={submitting}
            className="text-sm px-3 py-1.5 rounded-md border border-border
                       hover:bg-muted transition-colors">
            취소
          </button>
          <button type="button" onClick={onSubmit}
            disabled={submitting || amount <= 0}
            className="text-sm px-3 py-1.5 rounded-md bg-foreground
                       text-background hover:opacity-90 transition-opacity
                       disabled:opacity-50">
            {submitting ? "매수 중..." : "가상 매수"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function fmt(n: number): string {
  return n.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
}
