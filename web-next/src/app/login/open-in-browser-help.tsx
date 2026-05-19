"use client";

import { useEffect, useState } from "react";
import { Copy, ExternalLink } from "lucide-react";

/**
 * Helps the user escape an in-app WebView so Google OAuth works.
 *
 *   - Android: a `googlechrome://navigate?url=...` intent opens Chrome
 *     directly. Falls back gracefully if Chrome isn't installed (the
 *     intent just no-ops and they can still copy the URL).
 *   - iOS: there's no reliable scheme; the safest move is "long-press
 *     the URL, choose 'Open in Safari'", or just copy the URL.
 *   - Either platform: a one-click copy button.
 *
 * Rendered inside the WebView banner on /login when User-Agent indicates
 * KakaoTalk / Naver / FB / Instagram / etc.
 */
export function OpenInBrowserHelp() {
  const [url, setUrl] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [chromeScheme, setChromeScheme] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const here = window.location.href;
    setUrl(here);
    // Android-only escape hatch — strip protocol because the Chrome
    // intent expects bare host+path.
    const ua = navigator.userAgent;
    const isAndroid = /Android/i.test(ua);
    if (isAndroid) {
      const noProto = here.replace(/^https?:\/\//, "");
      setChromeScheme(`googlechrome://navigate?url=${encodeURIComponent(noProto)}`);
    }
  }, []);

  async function copy() {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Some in-app browsers (older KakaoTalk on iOS) don't expose the
      // Clipboard API. Fall back to selecting an input element so the
      // user can long-press → copy manually.
      const input = document.getElementById(
        "copy-fallback-input",
      ) as HTMLInputElement | null;
      if (input) {
        input.select();
        input.setSelectionRange(0, input.value.length);
      }
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={copy}
          className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-md bg-foreground text-background px-3 py-2 text-xs font-medium hover:opacity-90"
        >
          <Copy className="h-3.5 w-3.5" />
          {copied ? "복사됨!" : "주소 복사"}
        </button>
        {chromeScheme && (
          <a
            href={chromeScheme}
            className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-md border-2 border-foreground bg-background px-3 py-2 text-xs font-medium hover:bg-muted"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Chrome 에서 열기
          </a>
        )}
      </div>
      <input
        id="copy-fallback-input"
        readOnly
        value={url}
        className="w-full text-[11px] font-mono px-2 py-1 rounded border border-input bg-background"
        onFocus={(e) => e.target.select()}
        aria-label="현재 URL"
      />
      <p className="text-[11px] text-muted-foreground leading-relaxed">
        iOS 사용자는 위 주소를 복사한 뒤 Safari 주소창에 붙여넣고 이동하세요.
      </p>
    </div>
  );
}
