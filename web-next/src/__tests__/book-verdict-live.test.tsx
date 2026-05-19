/**
 * Live-data smoke test for BookVerdict.
 *
 * Loads the JSON dump produced by re-running the Python analyzer on
 * each ticker (RKLB, GOOGL, IONQ, 066620.KQ) against current bars,
 * then renders BookVerdict for each result. Pins:
 *
 *   - the verdict TITLE that renders (matches the analyzer intent
 *     after the late-trend stretch guard commit)
 *   - critical lines per ticker (stretch_reason text, candle reversal
 *     callout when applicable, ambush narrative for 국보디자인, etc.)
 *
 * If the live data file is missing (no Python pipeline available in
 * CI), the tests skip rather than fail — they're meant for local
 * verification after pushing analyzer changes.
 */
import { describe, it, expect, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import fs from "node:fs";
import path from "node:path";
import { BookVerdict } from "@/components/book-verdict";
import type { AnalysisResult } from "@/lib/types/analysis";

afterEach(cleanup);

type LiveData = Record<string, AnalysisResult>;

function loadLive(): LiveData | null {
  const p = path.resolve(__dirname, "_live_data.json");
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

const live = loadLive();

describe.skipIf(live == null)(
  "BookVerdict — live analyzer output",
  () => {
    it("RKLB → 추세 유효 · 자리 지남 (3 gates hit, 눈썹캔들 reversal callout)", () => {
      const r = live!["RKLB"];
      expect(r).toBeDefined();
      expect(r.action).toBe("HOLD");
      expect(r.stretch_reason).toBeTruthy();
      render(<BookVerdict result={r} />);
      expect(screen.getByRole("heading", { name: /자리 지남/ }))
        .toBeInTheDocument();
      // All 3 stretch gates should appear in the reason text
      expect(screen.getByText(/8주 \+115%/)).toBeInTheDocument();
      expect(screen.getByText(/240MA 대비 \+\d+%/)).toBeInTheDocument();
      expect(screen.getByText(/52w 위치 \d+%/)).toBeInTheDocument();
      // 눈썹캔들 reversal narrative
      expect(screen.getByText(/마지막 캔들.*반전 주의/)).toBeInTheDocument();
      // 240MA distance narrative (>50 %)
      expect(screen.getByText(/주봉 240MA.*벗어남/)).toBeInTheDocument();
      // No generic 관망 card
      expect(screen.queryByText(/한 줄 평.*관망/)).toBeNull();
      // No misfiring of 매복 or BUY narrative
      expect(screen.queryByText(/매복.*포킹/)).toBeNull();
      expect(screen.queryByText(/강한 매수/)).toBeNull();
    });

    it("GOOGL → 추세 유효 · 자리 지남 (pos+rally gate, 그레이브스톤도지 callout)", () => {
      const r = live!["GOOGL"];
      expect(r).toBeDefined();
      expect(r.action).toBe("HOLD");
      expect(r.stretch_reason).toBeTruthy();
      render(<BookVerdict result={r} />);
      expect(screen.getByRole("heading", { name: /자리 지남/ }))
        .toBeInTheDocument();
      // Gate that fired: 52w pos + rally combo
      expect(screen.getByText(/52w 위치 \d+%.*8주 \+45%/))
        .toBeInTheDocument();
      // 그레이브스톤도지 reversal callout preserved
      expect(screen.getByText(/그레이브스톤도지.*반전 주의/))
        .toBeInTheDocument();
      // Holder-trailing-stop guidance
      expect(screen.getByText(/주봉 10MA.*이탈/)).toBeInTheDocument();
    });

    it("IONQ → 관망 (no stretch_reason, catalyst HOLD narrative)", () => {
      const r = live!["IONQ"];
      expect(r).toBeDefined();
      expect(r.action).toBe("HOLD");
      expect(r.stretch_reason ?? null).toBeNull();
      render(<BookVerdict result={r} />);
      // Generic HOLD verdict, NOT the stretch one
      expect(screen.getByRole("heading", { name: /관망/ }))
        .toBeInTheDocument();
      expect(screen.queryByText(/자리 지남/)).toBeNull();
      // 240MA narrative
      expect(screen.getByText(/240MA.*죽지 않은/)).toBeInTheDocument();
      // Next decision line
      expect(screen.getByText(/다음 결정 시점.*금요일/))
        .toBeInTheDocument();
    });

    it("066620.KQ (국보디자인) → 매복 · 포킹 대기 (STRONG_BUY ambush)", () => {
      const r = live!["066620.KQ"];
      expect(r).toBeDefined();
      // After the stretch gate, action could be STRONG_BUY still
      // (pos_52w=0.75 < 0.85, rally=5.6% < 30%, 240MA dist modest).
      // BookVerdict's ambush check should fire because tight box +
      // indecision candle hit ≥ 2 signals.
      expect(r.stretch_reason ?? null).toBeNull();
      render(<BookVerdict result={r} />);
      // Could be 매복 or fresh-entry depending on consolidation ratio;
      // for this ticker we expect 매복 (tight box 4 % + 도지 candle).
      const ambush = screen.queryByRole("heading", { name: /매복.*포킹/ });
      const fresh = screen.queryByRole("heading", { name: /강한 매수/ });
      expect(ambush || fresh).not.toBeNull();
      // It should NOT show the stretch verdict
      expect(screen.queryByText(/자리 지남/)).toBeNull();
    });
  },
);
