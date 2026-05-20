/**
 * /themes — Naver Finance 테마 list. 추천/점수 X — 단순 list.
 *
 * 사용자가 테마 클릭 → /themes/[id] 에서 종목 list. 각 종목 클릭 →
 * /stocks/[ticker] 에서 책 정신 자동 분석. 사용자가 직접 검증.
 *
 * 2026-05-20 부활. 이전 (search-only pivot 시 dropped) 의
 * 추천/점수/시계열 (theme_daily) 은 완전 제거 — false-positive 우려 X.
 */
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getServerClient } from "@/lib/supabase";

export const dynamic = "force-dynamic";
export const revalidate = 3600; // 1시간 ISR — weekly cron 으로 갱신

type ThemeRow = {
  theme_id: number;
  name: string;
  members: number;
};

async function fetchThemes(): Promise<ThemeRow[]> {
  const sb = getServerClient();
  const { data, error } = await sb
    .from("themes")
    .select("theme_id, name, members")
    .order("members", { ascending: false })
    .limit(300);
  if (error || !data) {
    console.error("themes read:", error?.message);
    return [];
  }
  return data as unknown as ThemeRow[];
}

export default async function ThemesPage() {
  const themes = await fetchThemes();

  return (
    <div className="space-y-6 max-w-5xl">
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> 대시보드
      </Link>

      <header>
        <h1 className="text-2xl font-semibold tracking-tight">🏷️ 테마</h1>
        <p className="mt-1 text-sm text-muted-foreground leading-relaxed">
          Naver Finance 기반 한국 시장 테마 분류. 종목수가 많은 순.
          테마 클릭 → 종목 list. 각 종목의 책 정신 분석은 종목 페이지에서.
        </p>
      </header>

      <section className="rounded-xl border-2 border-zinc-500/30 bg-zinc-500/5 p-4 space-y-2">
        <div className="text-[10px] uppercase tracking-widest text-zinc-700 dark:text-zinc-300">
          💡 테마 활용법
        </div>
        <ul className="text-xs space-y-1 leading-relaxed text-muted-foreground">
          <li className="flex gap-2"><span>·</span><span>이 페이지는 <strong>분류만</strong> — 추천/점수 없음. 책 정신상 종목 결정은 본인 차트+펀더 검증 후.</span></li>
          <li className="flex gap-2"><span>·</span><span>예: 콜드플레이트 / AI 반도체 / 2차전지 같은 테마 찾을 때 사용.</span></li>
          <li className="flex gap-2"><span>·</span><span>테마 안의 종목 = 시장이 분류한 것. 실제 매출 비중 다양 — 본인 검증 필수.</span></li>
        </ul>
      </section>

      {themes.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 p-6 text-sm text-muted-foreground">
          테마 데이터 없음 — weekly cron 으로 동기화 됩니다.
        </div>
      ) : (
        <section>
          <div className="text-xs text-muted-foreground mb-2">
            총 <strong className="text-foreground">{themes.length}</strong> 테마
          </div>
          <ul className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {themes.map((t) => (
              <li key={t.theme_id}>
                <Link
                  href={`/themes/${t.theme_id}`}
                  className="flex items-baseline justify-between gap-2 rounded-lg border border-border bg-card p-3 hover:bg-muted/30 transition-colors"
                >
                  <span className="text-sm font-medium truncate">{t.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {t.members}종목
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
