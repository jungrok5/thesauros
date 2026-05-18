"use client";

/**
 * Subtle banner shown while KRX is in regular session (09:00-15:30 KST,
 * Mon-Fri). Reminds the reader that today's candle/close hasn't been
 * finalized — the book is explicit (p238-241) that intraday data is not
 * decision-grade.
 *
 * Server-rendered as nothing; the client effect picks the user's local
 * wall clock, converts to KST, and renders accordingly. Avoids
 * hydration mismatch by initial-render returning null.
 */
import { useEffect, useState } from "react";

type Status = "regular" | "after" | "weekend" | null;

function krxStatusNow(): Status {
  // Build a Date in KST regardless of where the user's browser is.
  const nowUtc = Date.now();
  const kst = new Date(nowUtc + 9 * 3600 * 1000);
  const day = kst.getUTCDay();    // 0=Sun 6=Sat (in KST wall-clock space)
  if (day === 0 || day === 6) return "weekend";
  const minutes = kst.getUTCHours() * 60 + kst.getUTCMinutes();
  const open = 9 * 60;
  const close = 15 * 60 + 30;
  if (minutes >= open && minutes < close) return "regular";
  return "after";
}

export function MarketHoursNotice() {
  const [status, setStatus] = useState<Status>(null);

  useEffect(() => {
    function tick() {
      setStatus(krxStatusNow());
    }
    tick();
    // Refresh every minute so the banner disappears at 15:30.
    const id = setInterval(tick, 60_000);
    return () => clearInterval(id);
  }, []);

  if (status !== "regular") return null;

  return (
    <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
      🕒 장중입니다 (KRX 09:00-15:30 KST). 표시된 가격·캔들은 마지막 거래일 종가
      기준이며 오늘 봉은 마감 후 확정됩니다.{" "}
      <span className="opacity-70">
        매매 결정은 종가가 확정된 뒤에 — 책: 장중 가격에 흔들리지 말 것.
      </span>
    </div>
  );
}
