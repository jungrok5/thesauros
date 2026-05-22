"""Daily-scan lifecycle pings — start + end notifications for the
admin's telegram.

Why: prior to this, the only signal that a cron actually ran was the
GitHub Actions email or the `cron_health.py` 2-hour stale alert. For
fast iteration we want a heartbeat: a "🤖 started" message at the top
of the run and a "✅ finished / ❌ failed" message at the end, with the
key delta vs. baseline visible inline so the admin doesn't need to
open the runner logs to know if something interesting happened.

Subcommands:
  start  — emit the start ping, capture pre-cron snapshot to disk
           ("`/tmp/cron_start_<run_id>.json`") so `end` can diff
  end    — emit the end ping, including duration + DB size + alerts
           sent in the cron window + eligibility coverage

CLI from inside a GitHub Actions step:

  python -m app.db.notify_admin_cron start
  ... (cron steps run) ...
  python -m app.db.notify_admin_cron end --status ${{ job.status }}

Reads:
  - ADMIN telegram_chat_id via cron_health.admin_chat_ids()
    (users where role = 'admin')
  - TELEGRAM_BOT_TOKEN from env
  - GITHUB_RUN_ID + GITHUB_SERVER_URL + GITHUB_REPOSITORY for the
    "View run ↗" link.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db import get_conn   # noqa: E402
from app.db.cron_health import admin_chat_ids, send_telegram  # noqa: E402

log = logging.getLogger("notify_admin_cron")

KST = timezone(timedelta(hours=9))


def _snapshot_path() -> Path:
    """Where `start` parks its baseline so `end` can diff. Uses
    GITHUB_RUN_ID when present so concurrent runs don't collide; falls
    back to a single file for ad-hoc local invocations."""
    run_id = os.environ.get("GITHUB_RUN_ID") or "local"
    # Prefer /tmp on linux runners; %TEMP% on Windows.
    base = Path(os.environ.get("RUNNER_TEMP") or "/tmp")
    if not base.exists():
        base = Path(".")
    return base / f"cron_start_{run_id}.json"


def _run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")


def _db_size_mb() -> float:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            return cur.fetchone()[0] / 1024 / 1024


def _capture_baseline() -> Dict[str, Any]:
    """Collect the rolled-up counts that `end` will diff against. Cheap
    queries only — this runs before the actual cron work."""
    snap: Dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "db_size_mb": round(_db_size_mb(), 1),
    }
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            for t in ("scan_results", "analyze_results", "alerts"):
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                snap[f"count_{t}"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scan_results WHERE is_active = true")
            snap["active_signals"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM analyze_results WHERE result ? 'eligibility'"
            )
            snap["with_eligibility"] = cur.fetchone()[0]
    return snap


def _alerts_in_window(since_iso: str) -> List[Dict[str, Any]]:
    """Alerts sent since the cron start. Used in the end ping so the
    admin sees what fired this run.

    sent_telegram 컬럼도 가져옴 — end-ping 의 deliver-rate observability
    (회고 #48/#49) 에 활용. sent=false 비율 높으면 silent fail 의심.
    """
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, alert_type, sent_at, "
                "       COALESCE(sent_telegram, false) AS sent_telegram "
                "  FROM alerts "
                " WHERE created_at >= %s "
                " ORDER BY created_at DESC LIMIT 100",
                (since_iso,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]


def _post_to_admins(text: str, dry_run: bool) -> int:
    chat_ids = admin_chat_ids()
    if not chat_ids:
        log.warning("no admin chat_ids registered — nothing to do")
        return 0
    if dry_run:
        log.info("DRY-RUN: would notify %d admins", len(chat_ids))
        log.info("message:\n%s", text)
        return 0
    sent = sum(send_telegram(c, text) for c in chat_ids)
    log.info("notified %d/%d admins", sent, len(chat_ids))
    return sent


# ─────────────────────────────────────────────────────────────────────
# Subcommands
# ─────────────────────────────────────────────────────────────────────

def cmd_start(dry_run: bool, label: str = "Daily-scan") -> int:
    """Emit the start ping. Captures baseline counts to a side file so
    the `end` command can compute deltas.

    `label` differentiates pings when multiple cron workflows share the
    same notification helper (daily-data vs weekly-scan vs ...).
    """
    baseline = _capture_baseline()
    path = _snapshot_path()
    try:
        path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        log.info("baseline written to %s", path)
    except OSError as e:
        # Not fatal — the start ping still goes out; end ping just
        # falls back to "delta unknown".
        log.warning("could not write baseline (%s): %s", path, e)

    run_url = _run_url()
    pct = baseline["db_size_mb"] / 500 * 100
    text = (
        f"🤖 <b>{label} 시작</b>\n"
        f"시각: {_now_kst()}\n"
        f"DB: {baseline['db_size_mb']:.1f} MB ({pct:.1f}%)\n"
        f"활성 신호: {baseline['active_signals']:,}건\n"
        f"eligibility 적재: "
        f"{baseline['with_eligibility']}/{baseline['count_analyze_results']:,}"
    )
    if run_url:
        text += f"\n👉 <a href=\"{run_url}\">실행 보기 ↗</a>"

    # ── DB 천장 가드 (회고 #52) ──────────────────────────────────────
    # Supabase Free 500MB 의 95% (475MB) 초과 시 ingest 진행하면 read-only
    # 진입 위험 → 모든 cron 즉시 abort. start-ping 은 abort 메시지로 발사
    # 한 후 exit(2) — 후속 step 들이 "if: always()" 가 아니면 skip 됨.
    # retention.py 의 90% trigger (VACUUM FULL bars) 와 별개의 외측 가드.
    SOFT_PCT = 90.0
    HARD_PCT = 95.0
    if pct >= HARD_PCT:
        alert = (
            f"🚨 <b>{label} 중단</b>\n"
            f"DB {baseline['db_size_mb']:.1f}MB ({pct:.1f}%) — HARD ceiling "
            f"({HARD_PCT}%) 초과. ingest 시 Supabase read-only 진입 위험.\n"
            f"즉시 VACUUM FULL bars 필요 또는 retention 정책 재검토.\n"
        )
        if run_url:
            alert += f"👉 <a href=\"{run_url}\">실행 보기 ↗</a>"
        _post_to_admins(alert, dry_run)
        log.error("aborting cron — db %.1f%% > %.1f%%", pct, HARD_PCT)
        return 2   # non-zero → workflow step fails
    elif pct >= SOFT_PCT:
        text = "⚠️ <b>WARNING</b> — DB 사용량 SOFT 경계 초과\n" + text

    sent = _post_to_admins(text, dry_run)
    return 0 if sent > 0 or dry_run else 2


def cmd_end(status: str, dry_run: bool, label: str = "Daily-scan") -> int:
    """Emit the end ping. `status` should be the GH Actions job.status
    value (success / failure / cancelled)."""
    path = _snapshot_path()
    baseline: Optional[Dict[str, Any]] = None
    if path.exists():
        try:
            baseline = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("could not read baseline (%s): %s", path, e)

    # End counts.
    now_snap = _capture_baseline()

    # Header — green/red/yellow per outcome.
    if status == "success":
        head_icon, head_label = "✅", "완료"
    elif status == "cancelled":
        head_icon, head_label = "🟡", "취소됨"
    elif status == "failure":
        head_icon, head_label = "❌", "실패"
    else:
        head_icon, head_label = "🔵", f"종료 ({status or 'unknown'})"

    lines = [
        f"{head_icon} <b>{label} {head_label}</b>",
        f"시각: {_now_kst()}",
    ]

    # Duration — fall back when baseline missing.
    if baseline and baseline.get("captured_at"):
        try:
            t0 = datetime.fromisoformat(baseline["captured_at"])
            now = datetime.now(timezone.utc)
            dur_s = int((now - t0).total_seconds())
            mins, secs = divmod(dur_s, 60)
            lines.append(f"소요: {mins}분 {secs}초")
        except Exception:
            pass

    # DB + delta.
    pct = now_snap["db_size_mb"] / 500 * 100
    if baseline:
        d_db = now_snap["db_size_mb"] - baseline.get("db_size_mb", 0)
        lines.append(
            f"DB: {now_snap['db_size_mb']:.1f} MB ({pct:.1f}%) "
            f"({'+' if d_db >= 0 else ''}{d_db:.1f}MB)"
        )
    else:
        lines.append(f"DB: {now_snap['db_size_mb']:.1f} MB ({pct:.1f}%)")

    # Eligibility coverage — confirms the analyzer wrote the field for
    # every row this cron touched.
    elig_now = now_snap.get("with_eligibility", 0)
    total = now_snap.get("count_analyze_results", 0)
    if total:
        cov = elig_now / total * 100
        lines.append(
            f"eligibility 적재: {elig_now:,}/{total:,} ({cov:.0f}%)"
        )

    # Alerts during this cron window (if we have a start time).
    if baseline and baseline.get("captured_at"):
        alerts = _alerts_in_window(baseline["captured_at"])
        # Group by alert_type for the summary line.
        by_type: Dict[str, int] = {}
        sent_count = 0
        for a in alerts:
            by_type[a["alert_type"]] = by_type.get(a["alert_type"], 0) + 1
            if a.get("sent_telegram"):
                sent_count += 1
        if alerts:
            summary = " · ".join(
                f"{t}={n}" for t, n in sorted(by_type.items())
            )
            lines.append(f"새 alert: {len(alerts)}건 · {summary}")
            # 관찰성 (회고 #48/#49): sent_telegram=true 비율이 낮으면
            # 모든 발송이 silent fail 중일 가능성. 50% 이하면 ⚠️ flag.
            if len(alerts) >= 3:   # 충분한 표본
                deliver_pct = sent_count / len(alerts) * 100
                if deliver_pct < 50:
                    lines.append(
                        f"⚠️ Telegram 발송 성공률: {sent_count}/{len(alerts)} "
                        f"({deliver_pct:.0f}%) — 토큰 / chat_id / Telegram "
                        "장애 확인 필요"
                    )
        else:
            lines.append("새 alert: 0건")

    # Row deltas — quick "did data move" sanity check.
    if baseline:
        for tbl, label in (("scan_results", "scan"),
                           ("analyze_results", "analyze"),
                           ("active_signals", "active")):
            now_v = now_snap.get(
                "active_signals" if tbl == "active_signals" else f"count_{tbl}"
            )
            base_v = baseline.get(
                "active_signals" if tbl == "active_signals" else f"count_{tbl}"
            )
            if isinstance(now_v, int) and isinstance(base_v, int):
                delta = now_v - base_v
                sign = "+" if delta >= 0 else ""
                lines.append(f"{label}: {now_v:,} ({sign}{delta:,})")

    run_url = _run_url()
    if run_url:
        lines.append(f"👉 <a href=\"{run_url}\">실행 보기 ↗</a>")

    text = "\n".join(lines)
    sent = _post_to_admins(text, dry_run)

    # Clean up baseline file — best effort.
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass

    return 0 if sent > 0 or dry_run else 2


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp_start = sub.add_parser("start", help="emit cron-start ping")
    sp_start.add_argument("--dry-run", action="store_true")
    sp_start.add_argument("--label", default="Daily-scan",
                           help="cron 이름 (메시지 헤더용). 기본 'Daily-scan'.")
    sp_end = sub.add_parser("end", help="emit cron-end ping")
    sp_end.add_argument("--status", default="success",
                        help="GH Actions job.status (success / failure / cancelled)")
    sp_end.add_argument("--dry-run", action="store_true")
    sp_end.add_argument("--label", default="Daily-scan",
                         help="cron 이름 (메시지 헤더용). start 와 같은 값.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.cmd == "start":
        return cmd_start(args.dry_run, args.label)
    if args.cmd == "end":
        return cmd_end(args.status, args.dry_run, args.label)
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
