"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Prefs = Record<string, boolean | string | null | number>;

interface Props {
  initialPrefs: Prefs | null;
  fields: Array<{ key: string; label: string; help: string }>;
}

export function AlertPrefsForm({ initialPrefs, fields }: Props) {
  const router = useRouter();
  const [prefs, setPrefs] = useState<Record<string, boolean>>(() => {
    const out: Record<string, boolean> = {};
    for (const f of fields) {
      out[f.key] = Boolean(initialPrefs?.[f.key] ?? true);
    }
    return out;
  });
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    try {
      const r = await fetch("/api/alert-preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prefs),
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
    <div className="space-y-3">
      <ul className="rounded-lg border border-border divide-y divide-border">
        {fields.map((f) => (
          <li key={f.key} className="flex items-start justify-between gap-3 p-3">
            <div className="flex-1">
              <div className="text-sm font-medium">{f.label}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{f.help}</div>
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
