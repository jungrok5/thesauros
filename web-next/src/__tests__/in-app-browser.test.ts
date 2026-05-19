/**
 * Tests for in-app browser detection.
 *
 * Google OAuth blocks embedded WebViews; users opening our link from
 * inside KakaoTalk / Naver / Facebook / Instagram hit the "허용되지
 * 않은 사용자 에이전트" dead-end. The /login page reads UA and shows
 * a banner instead — this test pins the patterns we recognize and
 * the ones we don't (real desktop / mobile browsers).
 *
 * UA samples are captured verbatim from real devices.
 */
import { describe, it, expect } from "vitest";
import { detectInAppBrowser } from "@/lib/in-app-browser";

describe("detectInAppBrowser", () => {
  it("flags KakaoTalk in-app browser (Android + iOS)", () => {
    const android =
      "Mozilla/5.0 (Linux; Android 14; SM-S918N Build/UP1A.231005.007; wv) " +
      "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.193 " +
      "Mobile Safari/537.36;KAKAOTALK 10.5.5";
    const ios =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KAKAOTALK 10.5.0";
    expect(detectInAppBrowser(android).app).toBe("KakaoTalk");
    expect(detectInAppBrowser(ios).app).toBe("KakaoTalk");
    expect(detectInAppBrowser(android).isInApp).toBe(true);
    expect(detectInAppBrowser(ios).isInApp).toBe(true);
  });

  it("flags Naver in-app browser", () => {
    const ua =
      "Mozilla/5.0 (Linux; Android 13; SM-A146P) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 " +
      "NAVER(inapp; search; 2000; 12.5.0)";
    expect(detectInAppBrowser(ua).app).toBe("Naver");
  });

  it("flags Facebook (FBAN/FBAV) including Messenger", () => {
    const fb =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;" +
      "FBAV/415.0.0;FBBV/463203448;FBDV/iPhone14,3]";
    expect(detectInAppBrowser(fb).app).toBe("Facebook");
  });

  it("flags Instagram", () => {
    const ua =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 " +
      "Instagram 296.0.0.34.110 (iPhone14,3; iOS 17_0; en_US; en;)";
    expect(detectInAppBrowser(ua).app).toBe("Instagram");
  });

  it("flags Line", () => {
    const ua =
      "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Version/4.0 Chrome/120.0.0.0 Mobile Safari/537.36 " +
      "Line/13.5.0";
    expect(detectInAppBrowser(ua).app).toBe("Line");
  });

  it("does NOT flag desktop Chrome", () => {
    const ua =
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
    expect(detectInAppBrowser(ua).isInApp).toBe(false);
  });

  it("does NOT flag mobile Safari", () => {
    const ua =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
    expect(detectInAppBrowser(ua).isInApp).toBe(false);
  });

  it("does NOT flag mobile Chrome", () => {
    const ua =
      "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 " +
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36";
    expect(detectInAppBrowser(ua).isInApp).toBe(false);
  });

  it("returns false for empty / null UA", () => {
    expect(detectInAppBrowser(null).isInApp).toBe(false);
    expect(detectInAppBrowser(undefined).isInApp).toBe(false);
    expect(detectInAppBrowser("").isInApp).toBe(false);
  });

  it("catches generic Android WebView via `; wv)` token", () => {
    // Custom apps not in our explicit pattern list (e.g. small Korean
    // banking apps) — still want the banner to fire so users escape.
    const ua =
      "Mozilla/5.0 (Linux; Android 13; XYZ Build/SP1A.210812.016; wv) " +
      "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 " +
      "Chrome/120.0.6099.193 Mobile Safari/537.36";
    expect(detectInAppBrowser(ua).isInApp).toBe(true);
    expect(detectInAppBrowser(ua).app).toBe("WebView");
  });
});
