"""A faithful PayPal HTTP surface for tests, backed by ``FakePayPalGateway``.

The real client is exercised end to end (URL building, auth, JSON round-trip,
error mapping) against an in-memory gateway, so one contract suite can run
against both implementations and prove they agree.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping

import httpx

from contracts import (
    Capture,
    Dispute,
    DisputeActionResult,
    GatewayTimeout,
    NotFoundError,
    Order,
    PayPalRejectedError,
    PayPalTransientError,
    Refund,
)

from .fake import FakePayPalGateway
from .money import from_minor, to_minor

__all__ = ["make_gateway_transport", "order_json", "capture_json", "dispute_json"]


def _dt(value: datetime) -> str:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def capture_json(capture: Capture) -> Dict[str, Any]:
    return {
        "id": capture.capture_id,
        "order_id": capture.order_id,
        "status": capture.status,
        "amount": {
            "currency_code": capture.currency,
            "value": from_minor(capture.amount_minor),
        },
        "seller_receivable_breakdown": {
            "refunded_amount": {
                "currency_code": capture.currency,
                "value": from_minor(capture.refunded_amount_minor),
            }
        },
        "create_time": _dt(capture.created_at),
    }


def order_json(order: Order) -> Dict[str, Any]:
    items = [
        {
            "name": item.name,
            "quantity": str(item.quantity),
            "unit_amount": {
                "currency_code": order.currency,
                "value": from_minor(item.unit_amount_minor),
            },
        }
        for item in order.items
    ]
    return {
        "id": order.order_id,
        "status": order.status,
        "create_time": _dt(order.created_at),
        "payer": {"email_address": order.payer_email},
        "purchase_units": [
            {
                "amount": {
                    "currency_code": order.currency,
                    "value": from_minor(order.amount_minor),
                },
                "items": items,
                "payments": {
                    "captures": [capture_json(capture) for capture in order.captures]
                },
            }
        ],
    }


def refund_json(refund: Refund) -> Dict[str, Any]:
    return {
        "id": refund.refund_id,
        "capture_id": refund.capture_id,
        "status": refund.status,
        "amount": {
            "currency_code": refund.currency,
            "value": from_minor(refund.amount_minor),
        },
        "create_time": _dt(refund.created_at),
    }


def dispute_json(dispute: Dispute) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dispute_id": dispute.dispute_id,
        "status": dispute.status,
        "reason": dispute.reason,
        "disputed_amount": {
            "currency_code": dispute.currency,
            "value": from_minor(dispute.amount_minor),
        },
        "create_time": _dt(dispute.created_at),
    }
    if dispute.order_id is not None:
        payload["order_id"] = dispute.order_id
    if dispute.capture_id is not None:
        payload["capture_id"] = dispute.capture_id
    if dispute.evidence_due_by is not None:
        payload["evidence_due_by"] = _dt(dispute.evidence_due_by)
    return payload


def _dispatch(request: httpx.Request, gateway: FakePayPalGateway) -> httpx.Response:
    path = request.url.path
    method = request.method
    parts = [part for part in path.split("/") if part]
    body: Mapping[str, Any] = {}
    if request.content:
        try:
            decoded = json.loads(request.content.decode("utf-8"))
            body = decoded if isinstance(decoded, dict) else {}
        except (ValueError, UnicodeDecodeError):
            body = {}

    if method == "GET" and parts[:3] == ["v2", "checkout", "orders"] and len(parts) == 4:
        return httpx.Response(200, json=order_json(gateway.get_order(parts[3])))

    if method == "GET" and parts[:3] == ["v2", "payments", "captures"] and len(parts) == 4:
        return httpx.Response(200, json=capture_json(gateway.get_capture(parts[3])))

    if (
        method == "POST"
        and parts[:3] == ["v2", "payments", "captures"]
        and len(parts) == 5
        and parts[4] == "refund"
    ):
        amount = body.get("amount") or {}
        refund = gateway.refund_capture(
            parts[3],
            to_minor(amount.get("value")),
            str(amount.get("currency_code", "")),
            request.headers.get("paypal-request-id", ""),
        )
        return httpx.Response(201, json=refund_json(refund))

    if method == "GET" and path == "/v1/customer/disputes":
        disputes = gateway.list_disputes()
        return httpx.Response(
            200, json={"items": [dispute_json(dispute) for dispute in disputes]}
        )

    if (
        method == "GET"
        and parts[:3] == ["v1", "customer", "disputes"]
        and len(parts) == 4
    ):
        return httpx.Response(200, json=dispute_json(gateway.get_dispute(parts[3])))

    if (
        method == "POST"
        and parts[:3] == ["v1", "customer", "disputes"]
        and len(parts) == 5
        and parts[4] == "provide-evidence"
    ):
        action = gateway.provide_dispute_evidence(
            parts[3],
            body.get("evidence") or {},
            request.headers.get("paypal-request-id", ""),
        )
        return httpx.Response(
            200, json={"dispute_id": action.dispute_id, "status": action.status}
        )

    if (
        method == "POST"
        and parts[:3] == ["v1", "customer", "disputes"]
        and len(parts) == 5
        and parts[4] == "accept-claim"
    ):
        action = gateway.accept_dispute_claim(
            parts[3], request.headers.get("paypal-request-id", "")
        )
        return httpx.Response(
            200, json={"dispute_id": action.dispute_id, "status": action.status}
        )

    if method == "POST" and path == "/v1/notifications/verify-webhook-signature":
        event = body.get("webhook_event") or {}
        raw = json.dumps(event).encode("utf-8")
        result = gateway.verify_webhook(
            {
                "paypal-transmission-id": str(body.get("transmission_id", "")),
                "paypal-transmission-sig": str(body.get("transmission_sig", "")),
            },
            raw,
        )
        status = "SUCCESS" if result.verified else "FAILURE"
        return httpx.Response(200, json={"verification_status": status})

    return httpx.Response(
        404, json={"name": "RESOURCE_NOT_FOUND", "message": path}
    )


def make_gateway_transport(
    gateway: FakePayPalGateway,
    access_token: str = "test-access-token",
    expires_in: int = 3600,
) -> httpx.MockTransport:
    """Build a ``MockTransport`` that behaves like PayPal for ``gateway``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": access_token,
                    "token_type": "Bearer",
                    "expires_in": expires_in,
                },
            )
        if request.headers.get("authorization", "") != "Bearer " + access_token:
            return httpx.Response(
                401,
                json={"name": "AUTHENTICATION_FAILURE", "message": "invalid token"},
            )
        try:
            return _dispatch(request, gateway)
        except GatewayTimeout as exc:
            return httpx.Response(
                504, json={"name": exc.code, "message": str(exc)}
            )
        except PayPalRejectedError as exc:
            status = exc.status if 400 <= exc.status < 500 else 422
            return httpx.Response(
                status, json={"name": exc.code, "message": str(exc)}
            )
        except PayPalTransientError as exc:
            status = exc.status if exc.status >= 500 else 500
            return httpx.Response(
                status, json={"name": exc.code, "message": str(exc)}
            )
        except NotFoundError as exc:
            return httpx.Response(
                404, json={"name": "RESOURCE_NOT_FOUND", "message": str(exc)}
            )

    return httpx.MockTransport(handler)
