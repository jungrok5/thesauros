/**
 * In-app browser (WebView) detection from User-Agent.
 *
 * Google OAuth refuses authentication from embedded WebViews with a
 * "Google Account: This browser or app may not be secure" / "허용되지
 * 않은 사용자 에이전트" error. Users opening our login link from inside
 * KakaoTalk / Naver / Facebook / Instagram in-app browsers are blocked
 * and have to manually open the link in their system browser.
 *
 * We detect the most common offenders on the server side and render a
 * "외부 브라우저에서 열어주세요" banner with a copy-URL button on
 * /login instead of (or in addition to) the Google sign-in button.
 *
 * Pure function so it's unit-testable; the route handler / page just
 * passes `req.headers.get("user-agent")` straight in.
 */

const PATTERNS: { app: string; re: RegExp }[] = [
  // KakaoTalk in-app browser. Both Android + iOS use these tokens.
  { app: "KakaoTalk", re: /KAKAOTALK/i },
  // Naver app (NAVER) + Naver Cafe (NAVER) — both ship the same UA token.
  { app: "Naver", re: /NAVER\(inapp;/i },
  // Daum / Kakao Story.
  { app: "Daum", re: /Daum|DaumApps/i },
  // Facebook (FBAN/FBAV/FB_IAB) — same family covers Messenger too.
  { app: "Facebook", re: /FBAN|FBAV|FB_IAB|FBIOS/i },
  // Instagram.
  { app: "Instagram", re: /Instagram/i },
  // Line.
  { app: "Line", re: /\bLine\//i },
  // Generic WebView markers — Android's `; wv)` token and the
  // WebView/x.x string used by some custom apps.
  { app: "WebView", re: /; wv\)|WebView/i },
];

export interface InAppDetection {
  /** True if any pattern matched. */
  isInApp: boolean;
  /** Friendly app name ("KakaoTalk", "Naver", …) or null. */
  app: string | null;
}

export function detectInAppBrowser(
  userAgent: string | null | undefined,
): InAppDetection {
  if (!userAgent) return { isInApp: false, app: null };
  for (const { app, re } of PATTERNS) {
    if (re.test(userAgent)) return { isInApp: true, app };
  }
  return { isInApp: false, app: null };
}
