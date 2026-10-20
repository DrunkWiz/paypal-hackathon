"""Signed, short-lived, single-order resolution tokens.

A token is bound to exactly one order. It is HMAC-signed so the customer link
cannot be edited to point at another order, and it expires after 14 days.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

from contracts import TokenError

__all__ = ["TOKEN_TTL_SECONDS", "sign_token", "verify_token"]

TOKEN_TTL_SECONDS = 14 * 24 * 60 * 60


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return _b64encode(digest)


def sign_token(
    payload: Dict[str, Any],
    secret: str,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
    now: Optional[int] = None,
) -> str:
    issued = int(time.time() if now is None else now)
    body = dict(payload)
    body["iat"] = issued
    body["exp"] = issued + int(ttl_seconds)
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _b64encode(raw) + "." + _sign(raw, secret)


def verify_token(token: str, secret: str, now: Optional[int] = None) -> Dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 1:
        raise TokenError("malformed token")
    encoded, signature = token.split(".", 1)
    try:
        raw = _b64decode(encoded)
    except Exception:
        raise TokenError("malformed token payload")

    expected = _sign(raw, secret)
    if not hmac.compare_digest(signature, expected):
        raise TokenError("bad token signature")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise TokenError("malformed token payload")
    if not isinstance(payload, dict):
        raise TokenError("malformed token payload")

    current = int(time.time() if now is None else now)
    if int(payload.get("exp", 0)) < current:
        raise TokenError("token expired")
    if not payload.get("order_id"):
        raise TokenError("token is not bound to an order")
    return payload
