"""Generate a VAPID key pair (one-shot, run once and save the output).

Usage:
    python -m app.db.vapid_keys

Writes nothing — prints two lines:
    VAPID_PUBLIC_KEY=<base64url>
    VAPID_PRIVATE_KEY=<base64url>

Add them to .env (server) and web-next/.env.local (with
NEXT_PUBLIC_VAPID_PUBLIC_KEY=<public key> for the browser bundle).
"""
from __future__ import annotations

import base64
import sys


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def main() -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        sys.stderr.write("pip install cryptography\n")
        return 1

    key = ec.generate_private_key(ec.SECP256R1())
    raw_private = key.private_numbers().private_value.to_bytes(32, "big")
    pub = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    print("VAPID_PUBLIC_KEY=" + _b64u(pub))
    print("VAPID_PRIVATE_KEY=" + _b64u(raw_private))
    return 0


if __name__ == "__main__":
    sys.exit(main())
