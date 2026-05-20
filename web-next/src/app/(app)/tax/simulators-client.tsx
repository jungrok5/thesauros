"use client";

import { useState } from "react";
import {
  estimateCapitalGainsTax,
  yearEndOptimizer,
  estimateIsaPensionTransferRefund,
} from "@/lib/tax-calc";

function num(s: string): number {
  const n = parseFloat(s.replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function fmtKrw(v: number): string {
  return Math.round(v).toLocaleString("ko-KR");
}

export function TaxSimulators() {
  return (
    <div className="space-y-6">
      <CapitalGainsCard />
      <YearEndOptimizerCard />
      <IsaTransferCard />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 1. 미국 양도세 계산
// ─────────────────────────────────────────────────────────────────────

function CapitalGainsCard() {
  const [gain, setGain] = useState("");
  const result = estimateCapitalGainsTax(num(gain));
  return (
    <section className="rounded-xl border border-border bg-card p-5 space-y-4">
      <header>
        <h2 className="text-base font-semibold tracking-tight">
          1. 🇺🇸 미국 주식 양도세 계산
        </h2>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          올해 누적 미국 주식 매매차익 입력 → 양도세 + 세후 손익.
        </p>
      </header>
      <div className="space-y-2">
        <label className="text-xs text-muted-foreground">
          올해 누적 차익 (원)
        </label>
        <input
          type="text"
          inputMode="numeric"
          value={gain}
          onChange={(e) => setGain(e.target.value)}
          placeholder="예: 5000000"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30 font-mono"
        />
      </div>
      <div className="rounded-md bg-muted/30 p-3 space-y-1.5">
        <Row label="과세 대상 (250 만 공제 후)" value={`${fmtKrw(result.taxableGain)} 원`} />
        <Row label="양도세 (22%)" value={`${fmtKrw(result.tax)} 원`} tone="warn" />
        <Row label="세후 손에 들어오는 금액" value={`${fmtKrw(result.netGain)} 원`} tone="good" />
      </div>
      <p className="text-xs leading-relaxed">💡 {result.oneLiner}</p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 2. 연말 절세 매도 시기 추천
// ─────────────────────────────────────────────────────────────────────

function YearEndOptimizerCard() {
  const [realized, setRealized] = useState("");
  const [unrealized, setUnrealized] = useState("");
  const result = yearEndOptimizer({
    realizedYtdKrw: num(realized),
    unrealizedPnLKrw: num(unrealized),
  });
  return (
    <section className="rounded-xl border-2 border-emerald-500/40 bg-emerald-500/5 p-5 space-y-4">
      <header>
        <h2 className="text-base font-semibold tracking-tight">
          2. 📅 연말 절세 매도 시기 추천
        </h2>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          올해 이미 확정된 차익 + 보유 중 평가손익 입력 → 12 월 매도 액션
          제안. 손실 종목 청산으로 세금 상쇄 가능.
        </p>
      </header>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            올해 누적 확정 차익 (원)
          </label>
          <input
            type="text"
            inputMode="numeric"
            value={realized}
            onChange={(e) => setRealized(e.target.value)}
            placeholder="예: 1500000"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30 font-mono"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            보유 평가손익 (원, 손실은 음수)
          </label>
          <input
            type="text"
            inputMode="numeric"
            value={unrealized}
            onChange={(e) => setUnrealized(e.target.value)}
            placeholder="예: -800000"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30 font-mono"
          />
        </div>
      </div>
      <div className="rounded-md bg-background/70 border border-border p-3 space-y-1.5">
        <Row
          label="남은 250 만 공제 한도"
          value={`${fmtKrw(result.remainingDeductKrw)} 원`}
          tone={result.remainingDeductKrw > 0 ? "good" : "warn"}
        />
        <Row
          label="손실 청산 상쇄 가능"
          value={`${fmtKrw(result.lossOffsetKrw)} 원`}
        />
        <Row
          label="총 면세 익절 가능 (합)"
          value={`${fmtKrw(result.taxFreeBudgetKrw)} 원`}
          tone="good"
        />
      </div>
      {result.actions.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-widest text-emerald-700 dark:text-emerald-300">
            🎯 추천 액션
          </div>
          <ul className="text-xs space-y-1.5 leading-relaxed">
            {result.actions.map((a, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-emerald-700 dark:text-emerald-300 shrink-0">·</span>
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────
// 3. ISA → 연금저축 이전 환급 계산
// ─────────────────────────────────────────────────────────────────────

function IsaTransferCard() {
  const [balance, setBalance] = useState("");
  const [highIncome, setHighIncome] = useState(false);
  const result = estimateIsaPensionTransferRefund({
    isaBalanceKrw: num(balance),
    highIncome,
  });
  return (
    <section className="rounded-xl border border-border bg-card p-5 space-y-4">
      <header>
        <h2 className="text-base font-semibold tracking-tight">
          3. 🎁 ISA 만기 → 연금저축 이전 환급
        </h2>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          ISA 3 년 만기 도래 시 잔액 일부를 연금저축으로 이전하면 추가 세액공제.
          1 회성 보너스 — 모르고 지나치면 손해.
        </p>
      </header>
      <div className="grid grid-cols-1 sm:grid-cols-[2fr_1fr] gap-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">
            ISA 만기 평가금액 (원)
          </label>
          <input
            type="text"
            inputMode="numeric"
            value={balance}
            onChange={(e) => setBalance(e.target.value)}
            placeholder="예: 50000000"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-foreground/30 font-mono"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground">소득 구간</label>
          <label className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={highIncome}
              onChange={(e) => setHighIncome(e.target.checked)}
              className="rounded border-input"
            />
            <span className="text-xs">종합소득 5,500 만 ↑</span>
          </label>
        </div>
      </div>
      <div className="rounded-md bg-muted/30 p-3 space-y-1.5">
        <Row
          label="연금저축 이전 가능"
          value={`${fmtKrw(result.transferableKrw)} 원`}
        />
        <Row
          label="추가 세액공제 (1 회성)"
          value={`${fmtKrw(result.extraRefundKrw)} 원`}
          tone="good"
        />
      </div>
      <p className="text-xs leading-relaxed">💡 {result.oneLiner}</p>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────────────

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "warn";
}) {
  const cls =
    tone === "good"
      ? "text-emerald-700 dark:text-emerald-300"
      : tone === "warn"
        ? "text-amber-700 dark:text-amber-300"
        : "text-foreground";
  return (
    <div className="flex items-baseline justify-between gap-2 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={`font-mono ${cls}`}>{value}</span>
    </div>
  );
}
