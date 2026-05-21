/**
 * Static-analysis regression for the 2026-05-21 sidebar work:
 *
 *   1. /welcome 페이지 존재 + 5 step 안내가 들어있어야 함 (사용자가 오면
 *      이 페이지에서 시작 — 누군가 페이지 지우면 fail).
 *   2. 사이드바 NAV_GROUPS 가 의도된 6 그룹 + admin 마지막 group.
 *      유저: "어드민인데 모바일에서 관리자 메뉴가 안 보여" — fix 후 회귀
 *      방지. group heading 텍스트 변경 / 삭제 / 순서 깨짐 catch.
 *   3. 사이드바가 NavList overflow-y-auto 처리하는지 — admin group 이
 *      많아진 NavList 에서 잘리는 회귀 안 나게.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const WELCOME_PATH = path.resolve(
  __dirname, "..", "app", "(app)", "welcome", "page.tsx",
);
const SIDEBAR_PATH = path.resolve(
  __dirname, "..", "components", "sidebar.tsx",
);

describe("/welcome page regression", () => {
  it("(app)/welcome/page.tsx 존재", () => {
    expect(fs.existsSync(WELCOME_PATH)).toBe(true);
  });

  it("5 step 모두 포함 — 핵심 단어 검증", () => {
    const src = fs.readFileSync(WELCOME_PATH, "utf8");
    // STEPS array 의 5 title 핵심 키워드
    expect(src).toMatch(/시장 분위기/);
    expect(src).toMatch(/종목 발견/);
    expect(src).toMatch(/한 줄 평이 결론/);
    expect(src).toMatch(/관심 종목.*EXIT|관심 종목.*알림/);
    expect(src).toMatch(/금요일 종가/);
  });

  it("amber 박스에 '매매는 안 할수록 좋다' 책 정신 핵심 포함", () => {
    const src = fs.readFileSync(WELCOME_PATH, "utf8");
    expect(src).toMatch(/매매는 안 할수록 좋다/);
  });
});

describe("sidebar group regression", () => {
  const src = fs.readFileSync(SIDEBAR_PATH, "utf8");

  it("6 그룹 heading 모두 정의 — 순서대로", () => {
    const orderedHeadings = [
      "📖 가이드",
      "📍 시장 분위기",
      "🔎 종목 발견",
      "📊 시장 모니터",
      "⭐ 내 종목",
      "⚙️ 시스템",
    ];
    let lastIdx = -1;
    for (const h of orderedHeadings) {
      const idx = src.indexOf(h);
      expect(idx, `heading "${h}" not found`).toBeGreaterThanOrEqual(0);
      expect(idx, `heading "${h}" out of order`).toBeGreaterThan(lastIdx);
      lastIdx = idx;
    }
  });

  it("admin group heading 존재 ('🔒 관리자')", () => {
    expect(src).toMatch(/🔒 관리자/);
  });

  it("/welcome 이 사이드바 NAV 에 link 됨", () => {
    expect(src).toMatch(/href:\s*["']\/welcome["']/);
  });

  it("NavList 영역에 overflow-y-auto — 긴 그룹 잘림 방지 (2026-05-21 모바일 admin 사라짐 fix)", () => {
    // Both desktop sidebar + mobile drawer should wrap NavList in
    // overflow-y-auto. We just assert the className appears at least
    // twice in the file (once per place).
    const matches = src.match(/overflow-y-auto/g) ?? [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});
