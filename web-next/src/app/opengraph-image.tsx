import { ImageResponse } from "next/og";

/**
 * Dynamic Open Graph image — rendered once per route compile, cached
 * by Vercel's edge. Picked up by:
 *   - Open Graph (Facebook, KakaoTalk, Slack, Discord, …)
 *   - Twitter Cards (`twitter:image` falls back to OG)
 *   - LinkedIn
 *
 * Next.js convention: a file at `app/opengraph-image.tsx` (or
 * `app/<route>/opengraph-image.tsx`) is automatically wired up;
 * we don't have to list it in `metadata.openGraph.images`.
 */

export const runtime = "edge";
export const alt = "Thesauros — 추세추종 캔들 분석 자동 스캐너";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OG() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          background:
            "linear-gradient(135deg, #0a0a0a 0%, #111 60%, #1f1410 100%)",
          color: "#f5f5f4",
          fontFamily: "ui-sans-serif, system-ui",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          {/* Candle glyphs — three red bullish + one blue bearish */}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <div style={{ width: 14, height: 60, background: "#ef4444", borderRadius: 2 }} />
            <div style={{ width: 14, height: 96, background: "#ef4444", borderRadius: 2 }} />
            <div style={{ width: 14, height: 72, background: "#3b82f6", borderRadius: 2 }} />
            <div style={{ width: 14, height: 120, background: "#ef4444", borderRadius: 2 }} />
          </div>
          <div
            style={{
              fontSize: 56,
              fontWeight: 700,
              letterSpacing: "-0.02em",
            }}
          >
            Thesauros
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div
            style={{
              fontSize: 64,
              fontWeight: 600,
              letterSpacing: "-0.03em",
              lineHeight: 1.1,
              color: "#fef2f2",
            }}
          >
            추세추종 캔들 분석
          </div>
          <div
            style={{
              fontSize: 32,
              color: "#a8a29e",
              lineHeight: 1.3,
            }}
          >
            KOSPI · KOSDAQ 매주 금요일 주봉 자동 스캔
          </div>
          <div
            style={{
              fontSize: 28,
              color: "#a8a29e",
              lineHeight: 1.3,
            }}
          >
            17 패턴 · 추세 · 4등분선 · 외국인·기관 매매 · 거시 5축
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 22,
            color: "#78716c",
          }}
        >
          <div style={{ display: "flex", gap: 24 }}>
            <span>🟢 매수</span>
            <span>🟡 추가매수</span>
            <span>🟠 경고</span>
            <span>🔴 청산</span>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <span style={{ color: "#22c55e" }}>●</span>
            <span>책 17 패턴 자동 알림</span>
          </div>
        </div>
      </div>
    ),
    size,
  );
}
