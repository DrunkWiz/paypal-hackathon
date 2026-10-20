"""Signed resolution tokens: single-order, tamper-proof, 14-day expiry."""

from __future__ import annotations

import base64

import pytest

from backend.api.tokens import TOKEN_TTL_SECONDS, sign_token, verify_token
from contracts import TokenError


def test_round_trip():
    token = sign_token(
        {"merchant_id": "m1", "order_id": "ORDER-1", "capture_id": "CAP-1"},
        "secret",
    )
    payload = verify_token(token, "secret")
    assert payload["merchant_id"] == "m1"
    assert payload["order_id"] == "ORDER-1"


def test_default_ttl_is_fourteen_days():
    assert TOKEN_TTL_SECONDS == 14 * 24 * 60 * 60


def test_bad_signature_is_rejected():
    token = sign_token({"order_id": "ORDER-1"}, "secret")
    with pytest.raises(TokenError):
        verify_token(token, "different-secret")


def test_tampered_payload_is_rejected():
    token = sign_token({"order_id": "ORDER-1"}, "secret")
    _encoded, signature = token.split(".", 1)
    forged = (
        base64.urlsafe_b64encode(
            b'{"order_id":"ORDER-2","exp":9999999999}'
        )
        .decode("ascii")
        .rstrip("=")
    )
    with pytest.raises(TokenError):
        verify_token(forged + "." + signature, "secret")


def test_expired_token_is_rejected():
    token = sign_token({"order_id": "ORDER-1"}, "secret", ttl_seconds=10, now=1000)
    with pytest.raises(TokenError):
        verify_token(token, "secret", now=2000)


def test_token_valid_before_expiry():
    token = sign_token({"order_id": "ORDER-1"}, "secret", ttl_seconds=10, now=1000)
    assert verify_token(token, "secret", now=1005)["order_id"] == "ORDER-1"


def test_token_must_be_bound_to_an_order():
    token = sign_token({"merchant_id": "m1"}, "secret")
    with pytest.raises(TokenError):
        verify_token(token, "secret")


def test_malformed_token_is_rejected():
    with pytest.raises(TokenError):
        verify_token("nonsense", "secret")
