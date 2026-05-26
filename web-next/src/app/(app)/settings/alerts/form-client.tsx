"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Prefs = Record<string, boolean | string | null | number>;

interface FieldDef {
  key: string;
  label: string;
  help: string;
}

interface CategoryDef {
  title: string;
  intro: string;
  fields: FieldDef[];
}

interface Props {
  initialPrefs: Prefs | null;
  categories: CategoryDef[];
  allFields: FieldDef[];
}

// 2026-05-26 site review: 8 toggles was too much for a new user. They
// either flipped everything ON (telegram flood → ignore all → miss the
// exit one that mattered) or kept defaults without understanding what
// each meant. Three named presets give a single-click answer + the
// underlying toggles still adjustable for power users.
const PRESETS: Record<
  string,
  { label: string; oneLiner: string; on: string[] }
> = {
  beginner: {
    label: "🌱 초보 (3개)",
    oneLiner: "매수 신호 · 즉시 청산 · 새 공시만. 책 정신상 매주 1번 결정에 필수인 3개.",
    on: ["enable_enter", "enable_exit", "enable_disclosure"],
  },
  book: {
    label: "📚 책 정신 (5개)",
    oneLiner: "초보 3개 + 피라미딩 / 경고 신호. 매주 결정 + 보유 종목 점검에 필요한 5개.",
    on: [
      "enable_enter", "enable_pyramid", "enable_warn", "enable_exit",
      "enable_disclosure",
    ],
  },
  all: {
    label: "🛎️ 전체 (8개)",
    oneLiner: "240MA 통과 / 4등분선 25% 깨짐까지 전부. 알림 빈도 높음.",
    on: [
      "enable_enter", "enable_pyramid", "enable_warn", "enable_exit",
      "enable_ma240_break", "enable_quarter_25_break", "enable_disclosure",
    ],
  },
};

export function AlertPrefsForm({ initialPrefs, categories, allFields }: Props) {
  const router = useRouter();

  // Per-toggle state for every alert field in every category.
  const [prefs, setPrefs] = useState<Record<string, boolean>>(() => {
    const out: Record<string, boolean> = {};
    for (const f of allFields) {
      out[f.key] = Boolean(initialPrefs?.[f.key] ?? true);
    }
    return out;
  });

  // Separate toggle for the book's 와병투자 mode — opting in flips ALL
  // immediate alerts to OFF and only sends a Friday-close weekly
  // digest. Implemented in telegram_worker as a short-circuit before
  // the per-pref gates. (book 2부 3장 정신)
  const [bedrest, setBedrest] = useState<boolean>(
    Boolean(initialPrefs?.bedrest_mode ?? false),
  );

  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  function applyPreset(name: keyof typeof PRESETS) {
    const preset = PRESETS[name];
    setPrefs(() => {
      const out: Record<string, boolean> = {};
      for (const f of allFields) out[f.key] = preset.on.includes(f.key);
      return out;
    });
    // Applying a preset implies "give me the dashboard signals" — flip
    // bedrest off so the chosen toggles actually fire. The user can
    // re-enable bedrest after if they want.
    setBedrest(false);
  }

  async function save() {
    setBusy(true);
    try {
      const r = await fetch("/api/alert-preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...prefs, bedrest_mode: bedrest }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSavedAt(new Date().toLocaleTimeString("ko-KR"));
      router.refresh();
    } catch (e) {
      alert(`저장 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* 🛌 와병투자 모드 — 책의 이상적 정신 ("한달 누워있다 말일
          1회만 확인"). 별도 박스로 시각 우위 + ON 시 아래 카테고리들이
          비활성화돼 보이게. */}
      <section
        className={
          "rounded-lg border-2 p-4 transition-colors " +
          (bedrest
            ? "border-violet-500/60 bg-violet-500/10"
            : "border-border bg-card")
        }
      >
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={bedrest}
            onChange={(e) => setBedrest(e.target.checked)}
            className="mt-0.5 h-4 w-4"
            data-testid="pref-bedrest_mode"
          />
          <div className="flex-1">
            <div className="text-sm font-semibold">
              🛌 와병투자 모드 (Bed-rest Mode)
            </div>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              책 정신: <em>&quot;한달 내내 누워있다 말일 1회만 확인&quot;</em>.
              매매는 안 할수록 좋다. ON 시 아래 모든 즉시 알림이 꺼지고
              <strong> 금요일 종가 후 주 1회 통합 요약</strong>만 받습니다.
              손가락이 자꾸 가는 분께 권장.
            </p>
          </div>
        </label>
      </section>

      {/* Preset shortcut — one click to set toggles below to a sane
          combination. Power users can still flip individual toggles
          afterward. */}
      <section className="rounded-lg border border-border bg-card p-4 space-y-2">
        <header>
          <h2 className="text-sm font-semibold">⚡ 알림 빠른 설정</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            한 번에 여러 토글을 set — 그 다음 아래에서 개별 조정 가능. 저장 버튼은 따로 누름.
          </p>
        </header>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {(Object.keys(PRESETS) as Array<keyof typeof PRESETS>).map((name) => {
            const preset = PRESETS[name];
            return (
              <button
                key={name}
                type="button"
                onClick={() => applyPreset(name)}
                data-testid={`preset-${name}`}
                className="text-left rounded-md border border-border bg-background p-2.5 hover:bg-accent transition-colors"
              >
                <div className="text-sm font-medium">{preset.label}</div>
                <div className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
                  {preset.oneLiner}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Category-grouped per-alert toggles. bedrest 모드 ON 이면
          시각적으로 dim 해서 "현재 무효" 임을 표시 (저장은 가능 —
          모드 OFF 로 돌리면 다시 살아남). */}
      <div className={bedrest ? "opacity-40 pointer-events-none" : ""}>
        {categories.map((cat) => (
          <section key={cat.title} className="space-y-2 mb-5">
            <header>
              <h2 className="text-sm font-semibold">{cat.title}</h2>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                {cat.intro}
              </p>
            </header>
            <ul className="rounded-lg border border-border divide-y divide-border">
              {cat.fields.map((f) => (
                <li
                  key={f.key}
                  className="flex items-start justify-between gap-3 p-3"
                >
                  <div className="flex-1">
                    <div className="text-sm font-medium">{f.label}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {f.help}
                    </div>
                  </div>
                  <label className="inline-flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={prefs[f.key]}
                      onChange={(e) =>
                        setPrefs((p) => ({ ...p, [f.key]: e.target.checked }))
                      }
                      className="h-4 w-4"
                      data-testid={`pref-${f.key}`}
                    />
                    <span className="text-xs text-muted-foreground select-none">
                      {prefs[f.key] ? "ON" : "OFF"}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        ))}

        {/* 🟠 가격 알림 — watchlist 행별 target/stop. 토글 아님. */}
        <section className="space-y-2 mb-5">
          <header>
            <h2 className="text-sm font-semibold">🟠 가격 알림</h2>
            <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
              watchlist 종목별 사용자 지정 — target / stop 가격에 도달하면
              알림. 장중 발사 가능 (자동 청산 보조).
            </p>
          </header>
          <div className="rounded-lg border border-dashed border-border bg-muted/20 p-3 text-xs text-muted-foreground">
            관심·보유 종목 페이지에서 <strong>목표가 / 손절가</strong>를 등록하면
            자동 알림이 활성화됩니다.
          </div>
        </section>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="px-4 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
        >
          {busy ? "저장 중..." : "저장"}
        </button>
        {savedAt && (
          <span className="text-xs text-muted-foreground">
            저장됨 · {savedAt}
          </span>
        )}
      </div>
    </div>
  );
}
