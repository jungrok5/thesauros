/**
 * Regression guard: /stocks/[ticker] 페이지에 "캐시된 분석" 배너가
 * 다시 들어오지 않도록 차단 (2026-05-20 제거).
 *
 * 배경: 주봉/월봉 pivot 후 scan_daily 는 금요일 17 KST 에만 의미있게
 * 갱신 (W bar 가 Mon-Thu 에 안 바뀜). 따라서 daily-기준 isAnalysisStale
 * 판정은 평일에 처음 열어보는 종목마다 매번 true → 매번 dispatch +
 * 배너 노출. 사용자 노이즈만 발생하고 실질 갱신은 없는 dead path.
 *
 * 함께 차단:
 *   - "캐시된 분석" 문자열 (banner UI)
 *   - cached.stale 분기 (logic)
 *   - isAnalysisStale import (dependency)
 *   - 페이지 내 dispatchAnalyzeTicker 자동 호출 (watchlist add 시점은
 *     api/watchlist/route.ts 가 별도로 dispatch 하므로 OK).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const PAGE = path.resolve(
  __dirname,
  "..",
  "app",
  "(app)",
  "stocks",
  "[ticker]",
  "page.tsx",
);

describe("/stocks/[ticker] no stale-cache banner regression guard", () => {
  const src = fs.readFileSync(PAGE, "utf8");

  it("page does not render the '캐시된 분석' banner", () => {
    expect(src).not.toMatch(/캐시된 분석/);
  });

  it("page does not reference cached.stale branch", () => {
    expect(src).not.toMatch(/cached\.stale/);
  });

  it("page does not import isAnalysisStale", () => {
    expect(src).not.toMatch(/isAnalysisStale/);
  });

  it("page does not auto-dispatch analyze-ticker (watchlist route does it)", () => {
    // The watchlist POST route still imports dispatchAnalyzeTicker — that's
    // fine and necessary. The /stocks/[ticker] page itself must not.
    expect(src).not.toMatch(/dispatchAnalyzeTicker\s*\(/);
  });
});
