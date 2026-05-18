import { ImageResponse } from "next/og";

/**
 * Dynamic favicon — replaces the static `next.svg` referenced by the
 * old manifest. Rendered once per build and edge-cached. Sufficient
 * for browser tab + bookmark thumbnails.
 */

export const runtime = "edge";
export const size = { width: 64, height: 64 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "center",
          gap: 3,
          background: "#0a0a0a",
          padding: 10,
          borderRadius: 12,
        }}
      >
        {/* Three candles: red bullish / blue bearish / red bullish */}
        <div style={{ width: 8, height: 26, background: "#ef4444", borderRadius: 1 }} />
        <div style={{ width: 8, height: 38, background: "#3b82f6", borderRadius: 1 }} />
        <div style={{ width: 8, height: 44, background: "#ef4444", borderRadius: 1 }} />
      </div>
    ),
    size,
  );
}
