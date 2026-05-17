"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type TokenState = { token: string; expires_at: string } | null;

export function TelegramLink({ connected }: { connected: boolean }) {
  const router = useRouter();
  const [token, setToken] = useState<TokenState>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (connected) return;
    let cancelled = false;
    fetch("/api/telegram/link-token")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (cancelled) return;
        if (b?.active) setToken({ token: b.active.token, expires_at: b.active.expires_at });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [connected]);

  async function issue() {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetch("/api/telegram/link-token", { method: "POST" });
      if (!r.ok) throw new Error(String(r.status));
      const b = await r.json();
      setToken({ token: b.token, expires_at: b.expires_at });
    } catch (e) {
      alert(`토큰 발급 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!confirm("텔레그램 연동을 해제하시겠습니까?")) return;
    setBusy(true);
    try {
      const r = await fetch("/api/telegram/link-token", { method: "DELETE" });
      if (!r.ok && r.status !== 404) throw new Error(String(r.status));
      router.refresh();
    } catch (e) {
      alert(`해제 실패: ${e}`);
    } finally {
      setBusy(false);
    }
  }

  if (connected) {
    return (
      <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3 text-sm flex items-center justify-between gap-3">
        <span>✅ 텔레그램 연동됨</span>
        <button
          type="button"
          onClick={disconnect}
          disabled={busy}
          className="text-xs text-muted-foreground hover:text-rose-500 disabled:opacity-50"
        >
          해제
        </button>
      </div>
    );
  }

  const cmd = token ? `/link ${token.token}` : "";

  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-sm space-y-3">
      <div className="font-medium text-amber-700 dark:text-amber-300">
        🔔 텔레그램 연동
      </div>
      <ol className="list-decimal pl-5 space-y-1 text-muted-foreground">
        <li>
          텔레그램에서{" "}
          <a
            href="https://t.me/candle_trend_bot"
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono underline"
          >
            @candle_trend_bot
          </a>{" "}
          열기
        </li>
        <li>아래 버튼을 눌러 일회용 연동 토큰 발급</li>
        <li>발급된 명령을 봇 채팅창에 그대로 붙여넣기</li>
        <li>이 페이지를 새로고침 → ✅ 연동됨 확인</li>
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={issue}
          disabled={busy}
          className="px-3 py-1.5 rounded bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "발급 중..." : token ? "토큰 재발급" : "토큰 발급"}
        </button>
        {token && (
          <>
            <code className="px-2 py-1 rounded bg-muted font-mono text-xs select-all">
              {cmd}
            </code>
            <button
              type="button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(cmd);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                } catch {
                  /* ignore */
                }
              }}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              {copied ? "✓ 복사됨" : "복사"}
            </button>
            <span className="text-xs text-muted-foreground" suppressHydrationWarning>
              유효 1시간 ·{" "}
              {new Date(token.expires_at).toLocaleTimeString("ko-KR")} 만료
            </span>
          </>
        )}
      </div>
    </div>
  );
}
