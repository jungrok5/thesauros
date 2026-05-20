/**
 * Regression guard: /glossary 페이지는 2026-05-20 제거됨.
 *
 * 이유: 사용자가 "용어집 페이지는 많기도 하고 궁금한거 여기서 찾기 힘들어"
 * 라며 인라인 툴팁 (HelpTip) + 한글 표기 + (정식용어) 패턴으로 통일.
 *
 * 이 테스트는 다음 두 가지를 보장한다:
 *   1) /glossary 라우트 디렉토리가 다시 생성되지 않음.
 *   2) 사이드바 NAV 에 /glossary 링크가 없음.
 *   3) 그러나 @/lib/glossary 라이브러리는 HelpTip 이 사용하므로 유지.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const appDir = path.resolve(__dirname, "..", "app", "(app)");
const sidebarPath = path.resolve(__dirname, "..", "components", "sidebar.tsx");
const glossaryLibPath = path.resolve(__dirname, "..", "lib", "glossary.ts");

describe("/glossary page removal regression guard", () => {
  it("(app)/glossary route directory does not exist", () => {
    const dir = path.join(appDir, "glossary");
    expect(fs.existsSync(dir)).toBe(false);
  });

  it("sidebar NAV does not reference /glossary route", () => {
    const src = fs.readFileSync(sidebarPath, "utf8");
    // Match the literal /glossary route in href contexts; the substring
    // would also appear in @/lib/glossary imports, so anchor on the route.
    expect(src).not.toMatch(/href:\s*["']\/glossary["']/);
  });

  it("@/lib/glossary library is preserved (HelpTip depends on it)", () => {
    expect(fs.existsSync(glossaryLibPath)).toBe(true);
    const src = fs.readFileSync(glossaryLibPath, "utf8");
    expect(src).toMatch(/export const GLOSSARY/);
  });

  it("glossary library contains PER / PBR / ROE entries (inline tooltip needs)", () => {
    const src = fs.readFileSync(glossaryLibPath, "utf8");
    expect(src).toMatch(/^\s*per:\s*\{/m);
    expect(src).toMatch(/^\s*pbr:\s*\{/m);
    expect(src).toMatch(/^\s*roe:\s*\{/m);
  });
});
