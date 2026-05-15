"""ML panel 자동 invalidation — source data hash 기반.

문제:
    `feature_panel_v3.parquet` 가 한 번 build 되면 영구 사용.
    그러나 가격/펀더멘털/매크로/인사이더 데이터가 update 돼도
    panel 은 자동 rebuild 안 됨 → stale panel 위험.

해결:
    Panel build 시 source 들의 fingerprint (max date / 행수) 모아서
    hash → `feature_panel_v3.hash.json` 저장.
    다음 load 시 현재 source hash 와 비교, 다르면 invalid → rebuild 필요 신호.

비유:
    OS 의 make / Bazel 의 build cache invalidation 과 동일 패턴.
    파일 timestamp → 변경 감지 → 의존성 트리 재컴파일.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

from app.config import MODEL_DIR
from app.data.pit_db import cursor


PANEL_PATH = Path(MODEL_DIR) / "feature_panel_v3.parquet"
HASH_PATH = Path(MODEL_DIR) / "feature_panel_v3.hash.json"


def compute_source_fingerprint() -> Dict[str, str]:
    """Hash all source data dependencies. Returns dict for transparency."""
    out: Dict[str, str] = {}
    with cursor() as con:
        # prices
        r = con.execute(
            "SELECT MAX(date), COUNT(*) FROM prices"
        ).fetchone()
        out["prices"] = f"{r[0]}|{r[1]}"

        # fundamentals (max filed_date for SEC, or max date for KR/DART)
        r = con.execute(
            "SELECT MAX(date), COUNT(*) FROM fundamentals"
        ).fetchone()
        out["fundamentals"] = f"{r[0]}|{r[1]}"

        # KR fundamentals separate (may be 0 if DART not ingested)
        r = con.execute(
            "SELECT COUNT(*) FROM fundamentals "
            "WHERE ticker LIKE '%.KS' OR ticker LIKE '%.KQ'"
        ).fetchone()
        out["fundamentals_kr"] = str(r[0])

        # macro (table name is `macro`, not `macro_indicators`)
        try:
            r = con.execute(
                "SELECT MAX(date), COUNT(*) FROM macro"
            ).fetchone()
            out["macro"] = f"{r[0]}|{r[1]}"
        except Exception:
            out["macro"] = "absent"

        # insider_transactions
        try:
            r = con.execute(
                "SELECT MAX(filed_date), COUNT(*) FROM insider_transactions"
            ).fetchone()
            out["insider_transactions"] = f"{r[0]}|{r[1]}"
        except Exception:
            out["insider_transactions"] = "absent"

        # delisted_tickers (Phase 2 — survivorship)
        try:
            r = con.execute(
                "SELECT MAX(delisting_date), COUNT(*) FROM delisted_tickers"
            ).fetchone()
            out["delisted_tickers"] = f"{r[0]}|{r[1]}"
        except Exception:
            out["delisted_tickers"] = "absent"
    return out


def compute_source_hash(fingerprint: Optional[Dict[str, str]] = None) -> str:
    fp = fingerprint or compute_source_fingerprint()
    payload = json.dumps(fp, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def save_panel_with_hash(panel: pd.DataFrame,
                           extra_meta: Optional[Dict] = None) -> str:
    """Save panel + source hash sidecar. Returns the hash string."""
    fp = compute_source_fingerprint()
    h = compute_source_hash(fp)
    panel.to_parquet(PANEL_PATH, index=False)
    meta = {
        "hash": h,
        "fingerprint": fp,
        "panel_shape": list(panel.shape),
        "date_range": [str(panel["date"].min()),
                        str(panel["date"].max())] if "date" in panel.columns else None,
        "n_tickers": int(panel["ticker"].nunique()) if "ticker" in panel.columns else None,
    }
    if extra_meta:
        meta.update(extra_meta)
    with open(HASH_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    return h


def is_panel_stale(panel_path: Path = PANEL_PATH,
                    hash_path: Path = HASH_PATH) -> Tuple[bool, str]:
    """Returns (is_stale, reason). True if panel needs rebuild."""
    if not panel_path.exists():
        return True, "panel parquet missing"
    if not hash_path.exists():
        return True, "hash sidecar missing (legacy panel - rebuild for safety)"
    try:
        with open(hash_path, encoding="utf-8") as f:
            meta = json.load(f)
        cached_hash = meta.get("hash")
        current_hash = compute_source_hash()
        if cached_hash != current_hash:
            return True, f"source hash changed: {cached_hash} → {current_hash}"
        return False, "panel up-to-date"
    except Exception as e:
        return True, f"hash file corrupted: {e}"


def load_panel_or_rebuild(rebuild_fn,
                           force_rebuild: bool = False,
                           verbose: bool = True) -> pd.DataFrame:
    """Load panel from disk if fresh, else call `rebuild_fn()` to recreate.

    rebuild_fn: callable returning a fresh panel DataFrame.
    """
    if not force_rebuild:
        stale, reason = is_panel_stale()
        if not stale:
            if verbose:
                print(f"[panel-cache] loading cached panel ({reason})")
            return pd.read_parquet(PANEL_PATH)
        if verbose:
            print(f"[panel-cache] rebuilding: {reason}")
    else:
        if verbose:
            print("[panel-cache] force rebuild requested")
    panel = rebuild_fn()
    save_panel_with_hash(panel)
    return panel


def cli_status() -> None:
    """Print panel status for CLI inspection."""
    print(f"Panel path: {PANEL_PATH}")
    print(f"Hash path:  {HASH_PATH}")
    print(f"Panel exists: {PANEL_PATH.exists()}")
    print(f"Hash exists:  {HASH_PATH.exists()}")
    stale, reason = is_panel_stale()
    print(f"Is stale: {stale} ({reason})")
    print()
    print("Current source fingerprint:")
    for k, v in compute_source_fingerprint().items():
        print(f"  {k:25s} = {v}")
    print(f"Current source hash: {compute_source_hash()}")
    if HASH_PATH.exists():
        print()
        with open(HASH_PATH, encoding="utf-8") as f:
            meta = json.load(f)
        print(f"Cached hash:  {meta.get('hash')}")
        print(f"Cached at:    {meta.get('date_range')}")
        print(f"Cached shape: {meta.get('panel_shape')}")


if __name__ == "__main__":
    cli_status()
