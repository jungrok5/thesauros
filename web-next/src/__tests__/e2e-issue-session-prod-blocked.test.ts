/**
 * Production safety guard — `/api/e2e-test/issue-session` route 는
 * dev/test 에서만 동작해야 한다. prod (Vercel production + preview)
 * 에서 활성화되면 외부에서 임의 user 세션 발급 가능 — 사이트 전체 보안
 * 우회.
 *
 * 회고 (#40 + 보안 검토 2026-05-22): public repo 라 누구나 route 위치
 * 알 수 있음. 다층 가드:
 *   1. NODE_ENV === "production" → 404
 *   2. VERCEL_ENV in {"production","preview"} → 404
 *   3. E2E_TEST_TOKEN 미설정 또는 16 chars 미만 → 404
 *   4. x-e2e-token 헤더 mismatch → 403
 *   5. ALLOW_E2E_IN_PROD=1 로 명시적 opt-in 시에만 1-3 우회
 *
 * 이 테스트가 route 소스의 가드 조건들이 모두 존재하는지 정적 검사.
 * accidentally 하나 제거 시 fail.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";


const ROUTE = path.resolve(
  __dirname, "..", "app", "api", "e2e-test", "issue-session", "route.ts",
);

describe("issue-session prod blocking guards", () => {
  const src = fs.readFileSync(ROUTE, "utf8");

  it("checks NODE_ENV === 'production'", () => {
    expect(src).toMatch(/NODE_ENV\s*===\s*["']production["']/);
  });

  it("checks VERCEL_ENV for 'production' AND 'preview'", () => {
    expect(src).toMatch(/VERCEL_ENV\s*===\s*["']production["']/);
    expect(src).toMatch(/VERCEL_ENV\s*===\s*["']preview["']/);
  });

  it("requires ALLOW_E2E_IN_PROD=1 to bypass", () => {
    expect(src).toMatch(/ALLOW_E2E_IN_PROD\s*===\s*["']1["']/);
  });

  it("returns 404 (not 401/403) when prod-blocked — anti-enumeration", () => {
    // 404 disguises the endpoint's existence. 401/403 would confirm
    // the route is real, helping attackers iterate. We pin 404.
    // Look at the route's first early-return guard.
    const block = src.match(
      /IS_PROD[\s\S]{0,400}status:\s*(\d+)/,
    );
    expect(block, "production-block branch not found").not.toBeNull();
    if (block) {
      expect(block[1]).toBe("404");
    }
  });

  it("requires E2E_TEST_TOKEN to be ≥ 16 chars", () => {
    expect(src).toMatch(/expected\.length\s*<\s*16/);
  });

  it("uses constant-time compare for the token header", () => {
    // Naive `===` token compare leaks timing. timingSafeEqual is the
    // Node stdlib equivalent of crypto.timingSafeEqual.
    expect(src).toMatch(/timingSafeEqual/);
  });
});
