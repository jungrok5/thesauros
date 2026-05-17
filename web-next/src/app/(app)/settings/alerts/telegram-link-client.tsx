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

      <details className="text-sm text-muted-foreground">
        <summary className="cursor-pointer font-medium text-foreground/80 hover:text-foreground">
          텔레그램이 처음이신가요? (눌러서 펼치기)
        </summary>
        <ol className="list-decimal pl-5 space-y-1.5 mt-2 text-xs">
          <li>
            <a
              href="https://telegram.org/"
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              텔레그램
            </a>{" "}
            앱 설치 — 모바일 (App Store / Google Play) 또는 데스크톱
            (Windows / Mac).
          </li>
          <li>
            전화번호로 가입 (무료). 카카오톡과 별개의 앱입니다.
          </li>
          <li>
            로그인 후 검색창에{" "}
            <code className="font-mono bg-muted px-1 rounded">@candle_trend_bot</code>{" "}
            입력 → 결과의 봇 클릭.
          </li>
          <li>
            아래 <strong>1단계</strong>의 링크로 바로 열면 검색 생략 가능합니다.
          </li>
        </ol>
      </details>

      <div>
        <div className="font-medium text-sm mb-2 text-foreground/80">
          연동 순서
        </div>
        <ol className="list-decimal pl-5 space-y-2 text-sm">
          <li>
            <a
              href="https://t.me/candle_trend_bot"
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono underline text-blue-600 dark:text-blue-400"
            >
              t.me/candle_trend_bot
            </a>{" "}
            클릭 → 텔레그램이 열리면{" "}
            <strong>SAVE / 시작 / START</strong> 버튼 누르기.
          </li>
          <li>
            봇 채팅창에{" "}
            <code className="font-mono bg-muted px-1 rounded">/start</code>{" "}
            입력 후 전송 — 봇이 도움말로 응답합니다.
          </li>
          <li>
            아래 <strong>토큰 발급</strong> 버튼 클릭. 발급된{" "}
            <code className="font-mono bg-muted px-1 rounded">/link 토큰값</code>{" "}
            형태의 명령이 나타납니다.
          </li>
          <li>
            <strong>복사</strong> 버튼 누르고 → 텔레그램 봇 채팅창에 붙여넣고
            → 전송.
          </li>
          <li>
            봇이{" "}
            <span className="text-emerald-700 dark:text-emerald-300">
              ✅ 연동 완료!
            </span>{" "}
            라고 답하면 끝. 이 페이지를 새로고침하면 위 상태가 바뀝니다.
          </li>
        </ol>
      </div>

      <div className="text-xs text-muted-foreground bg-muted/40 rounded p-2">
        💡 <strong>텔레그램을 안 쓰신다면?</strong> 이 단계를 건너뛰고 아래의{" "}
        <strong>📱 브라우저 푸시</strong> 만 켜셔도 됩니다. PC/모바일 브라우저로
        직접 알림이 옵니다.
      </div>
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
