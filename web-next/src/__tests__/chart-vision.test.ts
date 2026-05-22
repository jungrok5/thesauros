/**
 * Tests for the chart-vision MVP.
 *
 * Two layers:
 *   1. Prompt content — pin the 책 정신 rules so a future edit doesn't
 *      accidentally introduce hype words or remove a core rule.
 *   2. Page route presence — `/chart-vision` registered, sidebar
 *      menu entry exists.
 *
 * Live Anthropic API calls aren't exercised here — that's covered by
 * manual smoke from the page once the env var is set.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";
import {
  CHART_VISION_SYSTEM_PROMPT,
  CHART_VISION_USER_PROMPT,
} from "@/lib/chart-vision-prompt";

describe("chart-vision system prompt — 책 정신 invariants", () => {
  it("references the book's core analytical pillars", () => {
    // Removing any of these would silently degrade the analysis quality
    // because the LLM wouldn't be told to look for them.
    for (const keyword of [
      "10MA",        // 진정한 추세선
      "240MA",       // 최강 지지/저항
      "정배열",       // / 역배열
      "쌍바닥",       // 패턴 8가지 중 핵심
      "거래량",       // 선행성
      "4등분선",     // 책 시그니처
      "돌반지",       // 최강 매수 시그널
    ]) {
      expect(
        CHART_VISION_SYSTEM_PROMPT.includes(keyword),
        `system prompt must reference "${keyword}" — removing it weakens the analysis`,
      ).toBe(true);
    }
  });

  it("enforces no-hype tone (책 정신: 매매는 안 할수록 좋다)", () => {
    // The prompt itself must instruct the model to avoid these.
    // Past incidents have shown unconstrained vision models will say
    // "지금 사세요" given any uptrending chart.
    for (const banned of ["지금 사세요", "꼭 사라", "무조건"]) {
      expect(
        CHART_VISION_SYSTEM_PROMPT.includes(banned),
        `prompt should explicitly ban "${banned}"`,
      ).toBe(true);
    }
    // And require soft verbs.
    expect(CHART_VISION_SYSTEM_PROMPT).toMatch(/점검|검토|원칙대로/);
  });

  it("demands JSON output for the page client to parse", () => {
    expect(CHART_VISION_SYSTEM_PROMPT).toMatch(/JSON/);
    expect(CHART_VISION_USER_PROMPT).toMatch(/JSON/);
  });

  it("declares the response schema fields the client renders", () => {
    // ResultCard.tsx reads these keys — drift here breaks the UI.
    for (const field of [
      '"verdict"',
      '"trend"',
      '"patterns"',
      '"volume_signal"',
      '"ma_state"',
      '"ma240_position"',
      '"action_ask"',
      '"warnings"',
      '"confidence"',
    ]) {
      expect(CHART_VISION_SYSTEM_PROMPT.includes(field)).toBe(true);
    }
  });

  it("instructs the model NOT to guess when uncertain", () => {
    // The book is anti-overconfidence — wrong analysis is worse than
    // none. Force "판단 불가" instead of hallucination.
    expect(CHART_VISION_SYSTEM_PROMPT).toMatch(/판단 불가|추측 (?:안 함|금지)/);
  });
});


describe("chart-vision page is registered", () => {
  it("page.tsx exists at the expected route", () => {
    const p = path.resolve(__dirname, "..", "app", "(app)", "chart-vision", "page.tsx");
    expect(fs.existsSync(p)).toBe(true);
  });

  it("API route exists", () => {
    const p = path.resolve(
      __dirname, "..", "app", "api", "chart-vision", "analyze", "route.ts",
    );
    expect(fs.existsSync(p)).toBe(true);
  });

  it("sidebar menu links to /chart-vision", () => {
    const sidebar = fs.readFileSync(
      path.resolve(__dirname, "..", "components", "sidebar.tsx"),
      "utf8",
    );
    expect(sidebar).toMatch(/\/chart-vision/);
  });
});
