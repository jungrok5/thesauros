"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Pencil, Plus, Trash2, X, Check } from "lucide-react";
import { COLOR_OPTIONS, groupColorClass } from "./group-colors";

export type Group = {
  id: number;
  name: string;
  color: string | null;
  order_index: number;
};

export function GroupManager({ groups }: { groups: Group[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState<string>("zinc");
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState<string | null>(null);

  async function createGroup() {
    if (busy || !newName.trim()) return;
    setBusy(true);
    try {
      const r = await fetch("/api/watchlist-groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName.trim(), color: newColor }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.error === "duplicate name" ? "같은 이름 그룹 이미 있음" : (b.error ?? `${r.status}`));
      }
      setNewName("");
      setNewColor("zinc");
      setAdding(false);
      router.refresh();
    } catch (e) {
      alert(`그룹 추가 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(g: Group) {
    setEditId(g.id);
    setEditName(g.name);
    setEditColor(g.color);
  }

  async function saveEdit() {
    if (busy || editId == null || !editName.trim()) return;
    setBusy(true);
    try {
      const r = await fetch("/api/watchlist-groups", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: editId, name: editName.trim(), color: editColor }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({}));
        throw new Error(b.error === "duplicate name" ? "같은 이름 그룹 이미 있음" : (b.error ?? `${r.status}`));
      }
      setEditId(null);
      router.refresh();
    } catch (e) {
      alert(`수정 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteGroup(id: number, name: string) {
    if (busy) return;
    if (!confirm(`그룹 "${name}" 삭제하시겠습니까? 종목 자체는 보존되며 미분류로 이동합니다.`)) return;
    setBusy(true);
    try {
      const r = await fetch(`/api/watchlist-groups?id=${id}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`${r.status}`);
      router.refresh();
    } catch (e) {
      alert(`삭제 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="rounded-lg border border-border bg-card">
      <summary className="px-4 py-2.5 cursor-pointer text-xs font-semibold tracking-wider uppercase text-muted-foreground hover:text-foreground flex items-center justify-between">
        <span>📁 그룹 관리 ({groups.length})</span>
        <span className="text-[10px] text-muted-foreground/70">펼치기 ↓</span>
      </summary>
      <div className="px-4 pb-4 space-y-2">
        {groups.length === 0 && !adding && (
          <p className="text-xs text-muted-foreground">
            아직 그룹 없음. 아래 “+ 새 그룹” 으로 분류 시작.
          </p>
        )}
        {groups.map((g) => (
          <div
            key={g.id}
            className="flex items-center gap-2 flex-wrap p-2 rounded border border-border/50"
          >
            {editId === g.id ? (
              <>
                <input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="flex-1 min-w-[120px] px-2 py-1 rounded border border-input bg-background text-sm"
                  placeholder="그룹 이름"
                  autoFocus
                />
                <div className="flex gap-1">
                  {COLOR_OPTIONS.map((c) => (
                    <button
                      type="button"
                      key={c.key}
                      onClick={() => setEditColor(c.key)}
                      className={`w-6 h-6 rounded border ${c.cls} ${
                        editColor === c.key ? "ring-2 ring-foreground" : ""
                      }`}
                      aria-label={c.label}
                      title={c.label}
                    />
                  ))}
                </div>
                <button
                  type="button"
                  onClick={saveEdit}
                  disabled={busy}
                  className="text-xs px-2 py-1 rounded bg-foreground text-background hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1"
                >
                  <Check className="h-3 w-3" /> 저장
                </button>
                <button
                  type="button"
                  onClick={() => setEditId(null)}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  취소
                </button>
              </>
            ) : (
              <>
                <span
                  className={`inline-flex items-center px-2 py-1 rounded border text-xs ${groupColorClass(g.color)}`}
                >
                  📁 {g.name}
                </span>
                <div className="flex-1" />
                <button
                  type="button"
                  onClick={() => startEdit(g)}
                  className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
                  aria-label="그룹 이름/색상 변경"
                >
                  <Pencil className="h-3 w-3" /> 이름
                </button>
                <button
                  type="button"
                  onClick={() => deleteGroup(g.id, g.name)}
                  disabled={busy}
                  className="text-xs text-muted-foreground hover:text-rose-500 inline-flex items-center gap-1 disabled:opacity-50"
                  aria-label="그룹 삭제"
                >
                  <Trash2 className="h-3 w-3" /> 삭제
                </button>
              </>
            )}
          </div>
        ))}

        {adding ? (
          <div className="flex items-center gap-2 flex-wrap p-2 rounded border border-dashed border-border">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") createGroup();
                if (e.key === "Escape") {
                  setAdding(false); setNewName("");
                }
              }}
              placeholder="그룹 이름 (예: AI 테마)"
              className="flex-1 min-w-[160px] px-2 py-1 rounded border border-input bg-background text-sm"
              autoFocus
            />
            <div className="flex gap-1">
              {COLOR_OPTIONS.map((c) => (
                <button
                  type="button"
                  key={c.key}
                  onClick={() => setNewColor(c.key)}
                  className={`w-6 h-6 rounded border ${c.cls} ${
                    newColor === c.key ? "ring-2 ring-foreground" : ""
                  }`}
                  aria-label={c.label}
                  title={c.label}
                />
              ))}
            </div>
            <button
              type="button"
              onClick={createGroup}
              disabled={busy || !newName.trim()}
              className="text-xs px-2 py-1 rounded bg-foreground text-background hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1"
            >
              <Check className="h-3 w-3" /> 추가
            </button>
            <button
              type="button"
              onClick={() => { setAdding(false); setNewName(""); }}
              className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
            >
              <X className="h-3 w-3" /> 취소
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="text-xs px-2.5 py-1.5 rounded border border-dashed border-border text-muted-foreground hover:text-foreground hover:border-foreground/40 inline-flex items-center gap-1.5"
          >
            <Plus className="h-3 w-3" /> 새 그룹
          </button>
        )}

        <p className="text-[10px] text-muted-foreground/70 mt-2">
          💡 그룹은 보유 종목에는 적용되지 않습니다 — 관심 종목만 분류 가능.
          그룹 삭제 시 그 안의 종목은 “미분류” 로 이동 (종목 자체는 안 잃어버림).
        </p>
      </div>
    </details>
  );
}
