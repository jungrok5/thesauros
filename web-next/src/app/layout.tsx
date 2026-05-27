import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Production-ish absolute base for OG/Twitter cards. Resolution order:
//   1. NEXT_PUBLIC_SITE_URL  — explicit override (e.g. custom domain).
//   2. VERCEL_PROJECT_PRODUCTION_URL — the project's prod alias
//      (e.g. "thesauros2026.vercel.app"), stable across deploys.
//   3. VERCEL_URL — the per-deployment URL (e.g. "thesauros-km3y...").
//      Last resort because each push changes it, so a freshly-cached
//      KakaoTalk preview can point to a deployment that 404s.
//   4. localhost — dev fallback; social previews don't matter locally.
const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : process.env.VERCEL_URL
      ? `https://${process.env.VERCEL_URL}`
      : "http://localhost:3000");

const DESC =
  "한국 종목 (KOSPI / KOSDAQ) 매주 금요일 자동 주봉 스캔 — 17종 캔들 패턴 + " +
  "추세 + 4등분선 + 외국인·기관 매매 + 거시 5축 다이얼. 텔레그램·웹 푸시 알림. " +
  "17년 universe-honest 백테스트 검증 (L2 ranking — CAGR 20.65% / Sharpe 0.83 / DD 37.3%).";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Thesauros — 추세추종 캔들 분석 자동 스캐너",
    template: "%s · Thesauros",
  },
  description: DESC,
  applicationName: "Thesauros",
  keywords: [
    "주식", "종가매매", "추세추종", "캔들 분석", "쌍바닥", "돌반지",
    "KOSPI", "KOSDAQ", "코스피", "코스닥",
    "외국인 매매", "기관 매매", "거시 지표", "시장 레짐",
    "주봉 매매", "240MA", "백테스트", "모멘텀",
    "Korean stocks", "trend following", "candlestick patterns",
  ],
  authors: [{ name: "Thesauros" }],
  creator: "Thesauros",
  manifest: "/manifest.webmanifest",
  // Next.js convention: `app/icon.tsx` is auto-wired and emits the
  // <link rel="icon"> head tag; same for app/favicon.ico (default
  // tab favicon). No need to enumerate them here.
  appleWebApp: {
    capable: true,
    title: "Thesauros",
    statusBarStyle: "black-translucent",
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true },
  },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Thesauros",
    title: "Thesauros — 추세추종 캔들 분석 자동 스캐너",
    description: DESC,
    locale: "ko_KR",
    // Dynamic image is served by app/opengraph-image.tsx (Next.js
    // convention) so we don't list a static URL here — Next picks it
    // up automatically and emits og:image with the right dimensions.
  },
  twitter: {
    card: "summary_large_image",
    title: "Thesauros — 추세추종 캔들 분석",
    description: DESC,
  },
  category: "finance",
};

export const viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning is required because:
    //   1) next-themes sets `class="dark"` on <html> before React hydrates
    //   2) browser extensions inject attributes (data-wxt-integrated, etc.)
    <html
      lang="ko"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body
        suppressHydrationWarning
        className="min-h-full bg-background text-foreground"
      >
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
