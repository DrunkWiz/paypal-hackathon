"""Stub-transport tests: exact paths, headers and bodies the real client sends.

These do not prove PayPal accepts the calls (no credentials). They prove the
client builds the request the integration documents require.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx
import pytest

from backend.paypal import PayPalClient
from contracts import (
    GatewayTimeout,
    NotFoundError,
    PayPalRejectedError,
    PayPalTransientError,
)

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


class Recorder:
    """A transport that records every request and replies from a callable."""

    def __init__(self, responder):
        self.requests: List[httpx.Request] = []
        self._responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600},
            )
        return self._responder(request)

    def paths(self) -> List[str]:
        return [request.url.path for request in self.requests]

    def only(self, suffix: str) -> httpx.Request:
        matches = [r for r in self.requests if r.url.path.endswith(suffix)]
        assert len(matches) == 1, (suffix, self.paths())
        return matches[0]


def make_client(recorder: Recorder, clock=None) -> PayPalClient:
    return PayPalClient(
        "client-id",
        "client-secret",
        transport=httpx.MockTransport(recorder),
        webhook_id="WH-ID",
        clock=clock or (lambda: NOW),
    )


def test_refund_request_shape():
    def responder(request):
        return httpx.Response(
            201,
            json={
                "id": "REF-1",
                "capture_id": "CAP-1",
                "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "12.34"},
                "create_time": "2024-01-01T00:00:00Z",
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder)
    refund = client.refund_capture("CAP-1", 1234, "USD", "idem-1")

    assert refund.refund_id == "REF-1"
    assert refund.amount_minor == 1234
    assert refund.currency == "USD"

    call = recorder.only("/refund")
    assert call.method == "POST"
    assert call.url.path == "/v2/payments/captures/CAP-1/refund"
    assert call.headers["paypal-request-id"] == "idem-1"
    body = json.loads(call.content.decode("utf-8"))
    assert body == {"amount": {"currency_code": "USD", "value": "12.34"}}


def test_refund_uses_integer_string_not_float():
    def responder(request):
        return httpx.Response(
            201,
            json={
                "id": "REF-1",
                "capture_id": "CAP-1",
                "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "0.05"},
                "create_time": "2024-01-01T00:00:00Z",
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder)
    client.refund_capture("CAP-1", 5, "USD", "idem-1")
    body = json.loads(recorder.only("/refund").content.decode("utf-8"))
    assert body["amount"]["value"] == "0.05"


def test_oauth_uses_basic_auth_and_client_credentials():
    def responder(request):
        return httpx.Response(200, json={})

    recorder = Recorder(responder)
    client = make_client(recorder)
    try:
        client.get_order("ORDER-1")
    except Exception:
        pass

    token_call = recorder.only("/v1/oauth2/token")
    assert token_call.method == "POST"
    authorization = token_call.headers["authorization"]
    assert authorization.startswith("Basic ")
    decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
    assert decoded == "client-id:client-secret"
    assert token_call.content == b"grant_type=client_credentials"


def test_token_is_cached_across_calls():
    def responder(request):
        return httpx.Response(
            200,
            json={
                "id": "ORDER-1",
                "status": "COMPLETED",
                "purchase_units": [
                    {"amount": {"currency_code": "USD", "value": "50.00"}}
                ],
                "create_time": "2024-01-01T00:00:00Z",
                "payer": {"email_address": "buyer@example.com"},
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder)
    client.get_order("ORDER-1")
    client.get_order("ORDER-1")

    token_calls = [p for p in recorder.paths() if p == "/v1/oauth2/token"]
    assert len(token_calls) == 1


def test_token_refreshes_after_expiry():
    holder = {"now": NOW}

    def responder(request):
        return httpx.Response(
            200,
            json={
                "id": "ORDER-1",
                "status": "COMPLETED",
                "purchase_units": [
                    {"amount": {"currency_code": "USD", "value": "50.00"}}
                ],
                "create_time": "2024-01-01T00:00:00Z",
                "payer": {"email_address": "buyer@example.com"},
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder, clock=lambda: holder["now"])
    client.get_order("ORDER-1")
    holder["now"] = holder["now"] + timedelta(hours=2)
    client.get_order("ORDER-1")

    token_calls = [p for p in recorder.paths() if p == "/v1/oauth2/token"]
    assert len(token_calls) == 2


def test_get_order_path():
    def responder(request):
        return httpx.Response(
            200,
            json={
                "id": "ORDER-9",
                "status": "COMPLETED",
                "purchase_units": [
                    {"amount": {"currency_code": "USD", "value": "19.99"}}
                ],
                "create_time": "2024-01-01T00:00:00Z",
                "payer": {"email_address": "buyer@example.com"},
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder)
    order = client.get_order("ORDER-9")
    assert order.amount_minor == 1999
    call = recorder.only("/v2/checkout/orders/ORDER-9")
    assert call.method == "GET"


def test_get_capture_path():
    def responder(request):
        return httpx.Response(
            200,
            json={
                "id": "CAP-9",
                "order_id": "ORDER-9",
                "status": "COMPLETED",
                "amount": {"currency_code": "USD", "value": "19.99"},
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder)
    capture = client.get_capture("CAP-9")
    assert capture.amount_minor == 1999
    assert recorder.only("/v2/payments/captures/CAP-9").method == "GET"


def test_list_disputes_path():
    def responder(request):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "dispute_id": "D-1",
                        "status": "OPEN",
                        "reason": "ITEM_NOT_RECEIVED",
                        "disputed_amount": {"currency_code": "USD", "value": "5.00"},
                    }
                ]
            },
        )

    recorder = Recorder(responder)
    client = make_client(recorder)
    disputes = client.list_disputes()
    assert disputes[0].dispute_id == "D-1"
    assert disputes[0].amount_minor == 500
    assert recorder.only("/v1/customer/disputes").method == "GET"


def test_provide_evidence_path_and_header():
    def responder(request):
        return httpx.Response(200, json={"dispute_id": "D-1", "status": "EVIDENCE_PROVIDED"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    client.provide_dispute_evidence("D-1", {"note": "x"}, "ev-1")
    call = recorder.only("/provide-evidence")
    assert call.url.path == "/v1/customer/disputes/D-1/provide-evidence"
    assert call.headers["paypal-request-id"] == "ev-1"


def test_accept_claim_path_and_header():
    def responder(request):
        return httpx.Response(200, json={"dispute_id": "D-1", "status": "ACCEPTED"})

    recorder = Recorder(recorder_responder := responder)
    client = make_client(recorder)
    client.accept_dispute_claim("D-1", "ac-1")
    call = recorder.only("/accept-claim")
    assert call.url.path == "/v1/customer/disputes/D-1/accept-claim"
    assert call.headers["paypal-request-id"] == "ac-1"


def test_verify_webhook_posts_signature_fields():
    def responder(request):
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    payload = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.REFUNDED", "resource": {"id": "R-1"}}
    event = client.verify_webhook(
        {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-id": "CERT",
            "paypal-transmission-id": "T-1",
            "paypal-transmission-sig": "SIG",
            "paypal-transmission-time": "2024-01-01T00:00:00Z",
        },
        json.dumps(payload).encode("utf-8"),
    )
    assert event.verified is True
    call = recorder.only("/v1/notifications/verify-webhook-signature")
    body = json.loads(call.content.decode("utf-8"))
    assert body["webhook_id"] == "WH-ID"
    assert body["transmission_id"] == "T-1"
    assert body["transmission_sig"] == "SIG"
    assert body["auth_algo"] == "SHA256withRSA"
    assert body["webhook_event"] == payload


def test_verify_webhook_failure_status():
    def responder(request):
        return httpx.Response(200, json={"verification_status": "FAILURE"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    event = client.verify_webhook({"paypal-transmission-sig": "bad"}, b'{"id":"WH-1"}')
    assert event.verified is False


def test_500_maps_to_transient_error():
    def responder(request):
        return httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    with pytest.raises(PayPalTransientError):
        client.get_order("ORDER-1")


def test_504_maps_to_gateway_timeout():
    def responder(request):
        return httpx.Response(504, json={"name": "GATEWAY_TIMEOUT"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    with pytest.raises(GatewayTimeout):
        client.get_order("ORDER-1")


def test_422_maps_to_rejected():
    def responder(request):
        return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    with pytest.raises(PayPalRejectedError):
        client.get_order("ORDER-1")


def test_404_maps_to_not_found():
    def responder(request):
        return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})

    recorder = Recorder(responder)
    client = make_client(recorder)
    with pytest.raises(NotFoundError):
        client.get_order("ORDER-1")
