"""Web Push (RFC 8030) delivery for PWA notifications.

Reads VAPID keys from environment:
  - VAPID_PUBLIC_KEY    — base64url, matches NEXT_PUBLIC_VAPID_PUBLIC_KEY
  - VAPID_PRIVATE_KEY   — base64url, server-only
  - VAPID_CONTACT_EMAIL — "mailto:..." or "https://...", per spec

Uses `pywebpush` if installed; otherwise this module is a no-op (so the
existing telegram path keeps working in environments without it).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Tuple

log = logging.getLogger("webpush")

try:
    from pywebpush import WebPushException, webpush  # type: ignore
    _AVAILABLE = True
except Exception:                                     # pragma: no cover
    webpush = None                                    # type: ignore
    WebPushException = Exception                      # type: ignore
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE and bool(os.environ.get("VAPID_PRIVATE_KEY"))


def _vapid_claims() -> Dict[str, str]:
    contact = os.environ.get("VAPID_CONTACT_EMAIL") or "mailto:admin@example.com"
    return {"sub": contact}


def send_one(sub: Dict[str, Any], payload: Dict[str, Any], ttl: int = 3600) -> Tuple[bool, int]:
    """Returns (ok, status_code). status_code 0 means transport failure."""
    if not is_available():
        return False, 0
    try:
        r = webpush(
            subscription_info={
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            },
            data=json.dumps(payload),
            vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
            vapid_claims=_vapid_claims(),
            ttl=ttl,
        )
        status = getattr(r, "status_code", 201)
        return 200 <= status < 300, status
    except WebPushException as e:               # type: ignore[misc]
        status = getattr(getattr(e, "response", None), "status_code", 0) or 0
        if status in (404, 410):
            log.info("subscription gone (will be GC'd): %s", sub.get("endpoint"))
        else:
            log.warning("webpush failed: %s", e)
        return False, int(status)
    except Exception as e:                       # pragma: no cover
        log.warning("webpush error: %s", e)
        return False, 0


def send_many(subs: Iterable[Dict[str, Any]], payload: Dict[str, Any]) -> Dict[str, List[str]]:
    """Sends `payload` to every subscription. Returns {sent: [...], gone: [...]}.

    Gone endpoints (404/410) should be removed from `push_subscriptions`.
    """
    sent: List[str] = []
    gone: List[str] = []
    for s in subs:
        ok, status = send_one(s, payload)
        if ok:
            sent.append(s["endpoint"])
        elif status in (404, 410):
            gone.append(s["endpoint"])
    return {"sent": sent, "gone": gone}
