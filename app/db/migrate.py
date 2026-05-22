"""Migration runner — keeps Supabase schema reproducible from `migrations/*.sql`.

Usage (from project root):
    python -m app.db.migrate up                # apply pending
    python -m app.db.migrate status            # show applied/pending
    python -m app.db.migrate reset --confirm   # drop everything, reapply all
    python -m app.db.migrate up --target 002_rls.sql  # apply up to file

The runner tracks applied migrations in a `_migrations` table:
    name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ, checksum TEXT
A re-run of the same file is a no-op unless the checksum changed (warning + skip).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv

# Load .env from project root regardless of where this is called from
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.db.connection import get_conn   # noqa: E402


MIGRATIONS_DIR = _ROOT / "migrations"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _list_migration_files() -> List[Path]:
    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    return files


def _ensure_meta_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            checksum TEXT NOT NULL
        )
    """)
    # migrations_audit — append-only, 회고 #47. _migrations 가 reset 돼도
    # 여기는 잔존 → replay detection 의 source of truth.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS migrations_audit (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            runner TEXT,
            event_type TEXT NOT NULL DEFAULT 'apply'
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_migrations_audit_name "
        "ON migrations_audit (name)"
    )


def _audit_seen(cur, name: str) -> bool:
    """True if `name` has been applied before per audit history (even
    if _migrations was reset since). Use to detect replay."""
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM migrations_audit WHERE name = %s)",
        (name,),
    )
    return cur.fetchone()[0]


def _audit_record(cur, name: str, cksum: str, event_type: str = "apply") -> None:
    """Append an apply event. INSERT-only — never UPDATE/DELETE this row."""
    import os
    runner = (
        os.environ.get("GITHUB_ACTOR")
        or os.environ.get("USER")
        or os.environ.get("USERNAME")
        or "unknown"
    )
    cur.execute(
        "INSERT INTO migrations_audit (name, checksum, runner, event_type) "
        "VALUES (%s, %s, %s, %s)",
        (name, cksum, runner, event_type),
    )


def _applied_set(cur) -> dict:
    cur.execute("SELECT name, checksum FROM _migrations ORDER BY name")
    return {r[0]: r[1] for r in cur.fetchall()}


def cmd_status() -> int:
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            _ensure_meta_table(cur)
            applied = _applied_set(cur)
    files = _list_migration_files()
    print(f"Migrations dir: {MIGRATIONS_DIR}")
    print(f"Total files:   {len(files)}")
    print(f"Applied:       {len(applied)}\n")
    for f in files:
        local_sum = _checksum(f.read_text(encoding="utf-8"))
        if f.name in applied:
            mark = "[OK]" if applied[f.name] == local_sum else "[CHANGED!]"
        else:
            mark = "[PENDING]"
        print(f"  {mark:12s} {f.name}")
    return 0


def cmd_up(target: str | None = None) -> int:
    files = _list_migration_files()
    if not files:
        print("(no migrations found)")
        return 0
    if target:
        try:
            stop_idx = next(i for i, f in enumerate(files) if f.name == target)
        except StopIteration:
            print(f"target {target!r} not found")
            return 1
        files = files[:stop_idx + 1]

    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            _ensure_meta_table(cur)
            applied = _applied_set(cur)

            for f in files:
                text = f.read_text(encoding="utf-8")
                cksum = _checksum(text)
                if f.name in applied:
                    if applied[f.name] == cksum:
                        print(f"  skip   {f.name}  (already applied)")
                    else:
                        print(f"  WARN   {f.name}  (checksum changed: was "
                              f"{applied[f.name]}, now {cksum} — skipping; "
                              f"create new migration to alter)")
                    continue
                # Replay detection (회고 #47): _migrations 엔 없지만
                # migrations_audit 에는 있으면 이전에 적용한 적 있음
                # = _migrations reset 발생 신호. destructive replay 위험
                # 알림 + 명시적 confirm 없으면 abort.
                replay = _audit_seen(cur, f.name)
                event_type = "apply"
                if replay:
                    import os
                    if os.environ.get("MIGRATE_ALLOW_REPLAY") != "1":
                        print(
                            f"  ABORT  {f.name}: migrations_audit 에 이미 "
                            "기록됨 = _migrations 가 reset 됐을 가능성. "
                            "정말 재실행하려면 MIGRATE_ALLOW_REPLAY=1 env 로 "
                            "다시 실행. (회고 #47 — 022_drop_themes replay "
                            "사고 방지)"
                        )
                        return 2
                    event_type = "replay"
                    print(f"  REPLAY {f.name}  (MIGRATE_ALLOW_REPLAY=1)")

                print(f"  apply  {f.name}  ({cksum})")
                try:
                    cur.execute(text)
                    cur.execute(
                        "INSERT INTO _migrations (name, checksum) VALUES (%s, %s)",
                        (f.name, cksum),
                    )
                    _audit_record(cur, f.name, cksum, event_type)
                except Exception as e:
                    print(f"  FAIL   {f.name}: {e}")
                    return 1
    print("up: done")
    return 0


def cmd_reset(confirm: bool) -> int:
    if not confirm:
        print("Refusing to reset without --confirm")
        return 1
    print("Dropping public schema (DESTRUCTIVE)...")
    with get_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            # Drop all tables in public (keeps extensions). DROP SCHEMA CASCADE
            # would remove extensions too, which we don't want.
            cur.execute("""
                DO $$ DECLARE r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public')
                    LOOP
                        EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """)
    print("Reset done. Reapplying migrations...")
    return cmd_up()


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Supabase migration runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show applied / pending migrations")

    up = sub.add_parser("up", help="apply pending migrations")
    up.add_argument("--target", type=str, default=None,
                    help="apply up to and including this filename")

    reset = sub.add_parser("reset", help="drop all tables and reapply (DESTRUCTIVE)")
    reset.add_argument("--confirm", action="store_true",
                       help="required to actually reset")

    args = p.parse_args(argv)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "up":
        return cmd_up(target=args.target)
    if args.cmd == "reset":
        return cmd_reset(confirm=args.confirm)
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
