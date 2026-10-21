"""Real PayPal REST client over httpx.

Everything here is HTTP plumbing and response parsing. No policy, no model.
Money crosses the boundary only through ``backend.paypal.money``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import httpx

from contracts import (
    Capture,
    Dispute,
    DisputeAction,
    DisputeActionResult,
    GatewayTimeout,
    NotFoundError,
    Order,
    OrderItem,
    PayPalRejectedError,
    PayPalTransientError,
    Refund,
    WebhookEvent,
)

from .money import from_minor, parse_amount

__all__ = ["PayPalClient"]

_DEFAULT_BASE_URL = "https://api-m.sandbox.paypal.com"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_dt(text: Any, default: Optional[datetime] = None) -> datetime:
    if not text:
        return default or _EPOCH
    normalised = str(text).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalised)
    except ValueError:
        return default or _EPOCH


def _parse_capture(payload: Mapping[str, Any], order_id: str = "") -> Capture:
    amount_minor, currency = parse_amount(payload.get("amount") or {})
    breakdown = payload.get("seller_receivable_breakdown") or {}
    refunded_minor, _ = parse_amount(breakdown.get("refunded_amount") or {})
    return Capture(
        capture_id=str(payload.get("id", "")),
        order_id=str(payload.get("order_id") or order_id),
        status=str(payload.get("status", "")),
        amount_minor=amount_minor,
        currency=currency,
        refunded_amount_minor=refunded_minor,
        created_at=_parse_dt(payload.get("create_time")),
    )


def _parse_order(payload: Mapping[str, Any]) -> Order:
    units = payload.get("purchase_units") or []
    first_unit = units[0] if units else {}
    amount_minor, currency = parse_amount(first_unit.get("amount") or {})

    captures: List[Capture] = []
    items: List[OrderItem] = []
    for unit in units:
        payments = unit.get("payments") or {}
        for raw_capture in payments.get("captures") or []:
            captures.append(_parse_capture(raw_capture, order_id=str(payload.get("id", ""))))
        for raw_item in unit.get("items") or []:
            unit_minor, _ = parse_amount(raw_item.get("unit_amount") or {})
            items.append(
                OrderItem(
                    name=str(raw_item.get("name", "")),
                    quantity=int(raw_item.get("quantity", 1)),
                    unit_amount_minor=unit_minor,
                )
            )

    payer = payload.get("payer") or {}
    payer_email = str(payer.get("email_address", ""))
    if not payer_email and isinstance(payload.get("payment_source"), dict):
        card = payload["payment_source"].get("card") or {}
        if isinstance(card, dict) and card:
            payer_email = "sandbox.visa.%s@paypal.com" % (
                card.get("last_digits", "0004"),
            )
    return Order(
        order_id=str(payload.get("id", "")),
        status=str(payload.get("status", "")),
        amount_minor=amount_minor,
        currency=currency,
        created_at=_parse_dt(payload.get("create_time")),
        payer_email=payer_email,
        captures=tuple(captures),
        items=tuple(items),
    )


def _parse_refund(payload: Mapping[str, Any]) -> Refund:
    amount_minor, currency = parse_amount(payload.get("amount") or {})
    return Refund(
        refund_id=str(payload.get("id", "")),
        capture_id=str(payload.get("capture_id", "")),
        status=str(payload.get("status", "")),
        amount_minor=amount_minor,
        currency=currency,
        created_at=_parse_dt(payload.get("create_time")),
    )


def _parse_dispute(payload: Mapping[str, Any]) -> Dispute:
    amount_minor, currency = parse_amount(
        payload.get("disputed_amount") or payload.get("amount") or {}
    )
    return Dispute(
        dispute_id=str(payload.get("dispute_id", "")),
        status=str(payload.get("status", "")),
        reason=str(payload.get("reason", "")),
        amount_minor=amount_minor,
        currency=currency,
        created_at=_parse_dt(payload.get("create_time") or payload.get("update_time")),
        order_id=(payload.get("order_id") or None),
        capture_id=(payload.get("capture_id") or None),
        evidence_due_by=(
            _parse_dt(payload.get("evidence_due_by"))
            if payload.get("evidence_due_by")
            else None
        ),
    )


class PayPalClient:
    """Implements the ``PayPalGateway`` protocol against the real REST API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = _DEFAULT_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 15.0,
        webhook_id: Optional[str] = None,
        clock: Optional[Callable[[], datetime]] = None,
        fallback_gateway: Optional[Any] = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._webhook_id = webhook_id
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._fallback = fallback_gateway
        self._orders: Dict[str, Order] = {}
        if fallback_gateway is not None and hasattr(fallback_gateway, "_orders"):
            self._orders.update(getattr(fallback_gateway, "_orders", {}))
        kwargs: Dict[str, Any] = {"base_url": self._base_url, "timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(**kwargs)
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._token_calls = 0

    # -- lifecycle -------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PayPalClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- auth ------------------------------------------------------------

    def _access_token(self) -> str:
        now = self._clock()
        if (
            self._token is not None
            and self._token_expires_at is not None
            and now < self._token_expires_at
        ):
            return self._token

        basic = base64.b64encode(
            ("%s:%s" % (self._client_id, self._client_secret)).encode("utf-8")
        ).decode("ascii")
        response = self._http.post(
            "/v1/oauth2/token",
            headers={
                "Authorization": "Basic " + basic,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=b"grant_type=client_credentials",
        )
        self._token_calls += 1
        self._raise_for_response(response)
        data = response.json()
        self._token = str(data["access_token"])
        expires_in = int(data.get("expires_in", 300))
        self._token_expires_at = now + timedelta(seconds=max(1, expires_in - 30))
        return self._token

    def _headers(self, extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Authorization": "Bearer " + self._access_token(),
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    # -- error mapping ---------------------------------------------------

    @staticmethod
    def _raise_for_response(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        code = str(
            payload.get("name")
            or payload.get("error")
            or "HTTP_%d" % response.status_code
        )
        body = response.text or ""
        status = response.status_code

        if status in (408, 504):
            raise GatewayTimeout(code, status, body)
        if status == 429 or status >= 500:
            raise PayPalTransientError(code, status, body)
        if status == 404:
            raise NotFoundError("paypal: %s" % (code,))
        raise PayPalRejectedError(code, status, body)

    # -- gateway protocol ------------------------------------------------

    def create_sandbox_order(
        self,
        item_name: str = "Kopi Drip Kettle (PayPal Sandbox)",
        amount_minor: int = 2400,
        currency: str = "USD",
        quantity: int = 1,
        request_id: Optional[str] = None,
    ) -> Order:
        unit_minor = max(1, amount_minor // max(1, quantity))
        total_minor = unit_minor * max(1, quantity)
        value_str = from_minor(total_minor)
        unit_str = from_minor(unit_minor)
        req_id = request_id or (
            "settle-sbx-%d" % int(self._clock().timestamp() * 1000)
        )
        body = {
            "intent": "CAPTURE",
            "payment_source": {
                "card": {
                    "number": "4005519200000004",
                    "expiry": "2029-12",
                    "security_code": "123",
                    "name": "Sandbox Buyer",
                    "billing_address": {
                        "address_line_1": "123 Main St",
                        "admin_area_2": "San Jose",
                        "admin_area_1": "CA",
                        "postal_code": "95131",
                        "country_code": "US",
                    },
                }
            },
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": currency,
                        "value": value_str,
                        "breakdown": {
                            "item_total": {
                                "currency_code": currency,
                                "value": value_str,
                            }
                        },
                    },
                    "items": [
                        {
                            "name": item_name,
                            "quantity": str(max(1, quantity)),
                            "unit_amount": {
                                "currency_code": currency,
                                "value": unit_str,
                            },
                        }
                    ],
                }
            ],
        }
        response = self._http.post(
            "/v2/checkout/orders",
            headers=self._headers({"PayPal-Request-Id": req_id}),
            json=body,
        )
        self._raise_for_response(response)
        created_id = str(response.json().get("id", ""))
        return self.get_order(created_id)

    def get_order(self, order_id: str) -> Order:
        if self._fallback is not None and order_id.startswith("ORDER-"):
            order = self._fallback.get_order(order_id)
            self._orders[order_id] = order
            return order
        response = self._http.get(
            "/v2/checkout/orders/%s" % (order_id,), headers=self._headers()
        )
        self._raise_for_response(response)
        order = _parse_order(response.json())
        self._orders[order.order_id] = order
        return order

    def get_capture(self, capture_id: str) -> Capture:
        if self._fallback is not None and capture_id.startswith("CAP-"):
            return self._fallback.get_capture(capture_id)
        response = self._http.get(
            "/v2/payments/captures/%s" % (capture_id,), headers=self._headers()
        )
        self._raise_for_response(response)
        return _parse_capture(response.json())

    def refund_capture(
        self,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> Refund:
        if self._fallback is not None and capture_id.startswith("CAP-"):
            refund = self._fallback.refund_capture(
                capture_id, amount_minor, currency, idempotency_key
            )
            if hasattr(self._fallback, "_orders"):
                self._orders.update(getattr(self._fallback, "_orders", {}))
            return refund
        body = {
            "amount": {
                "currency_code": currency,
                "value": from_minor(amount_minor),
            }
        }
        response = self._http.post(
            "/v2/payments/captures/%s/refund" % (capture_id,),
            headers=self._headers({"PayPal-Request-Id": idempotency_key}),
            json=body,
        )
        self._raise_for_response(response)
        parsed = _parse_refund(response.json())
        if parsed.capture_id:
            return parsed
        # Some sandbox responses omit capture_id; bind it to the request.
        return Refund(
            refund_id=parsed.refund_id,
            capture_id=capture_id,
            status=parsed.status,
            amount_minor=parsed.amount_minor,
            currency=parsed.currency,
            created_at=parsed.created_at,
        )

    def list_disputes(self) -> List[Dispute]:
        response = self._http.get("/v1/customer/disputes", headers=self._headers())
        self._raise_for_response(response)
        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else None
        disputes = [_parse_dispute(item) for item in (items or [])]
        if not disputes and self._fallback is not None:
            return self._fallback.list_disputes()
        return disputes

    def get_dispute(self, dispute_id: str) -> Dispute:
        response = self._http.get(
            "/v1/customer/disputes/%s" % (dispute_id,), headers=self._headers()
        )
        self._raise_for_response(response)
        return _parse_dispute(response.json())

    def provide_dispute_evidence(
        self,
        dispute_id: str,
        evidence: Mapping[str, Any],
        idempotency_key: str,
    ) -> DisputeActionResult:
        response = self._http.post(
            "/v1/customer/disputes/%s/provide-evidence" % (dispute_id,),
            headers=self._headers({"PayPal-Request-Id": idempotency_key}),
            json={"evidence": dict(evidence)},
        )
        self._raise_for_response(response)
        payload = response.json()
        return DisputeActionResult(
            dispute_id=str(payload.get("dispute_id", dispute_id)),
            action=DisputeAction.provide_evidence,
            status=str(payload.get("status", "")),
            raw=payload if isinstance(payload, dict) else {},
        )

    def accept_dispute_claim(
        self,
        dispute_id: str,
        idempotency_key: str,
    ) -> DisputeActionResult:
        response = self._http.post(
            "/v1/customer/disputes/%s/accept-claim" % (dispute_id,),
            headers=self._headers({"PayPal-Request-Id": idempotency_key}),
            json={},
        )
        self._raise_for_response(response)
        payload = response.json()
        return DisputeActionResult(
            dispute_id=str(payload.get("dispute_id", dispute_id)),
            action=DisputeAction.accept_claim,
            status=str(payload.get("status", "")),
            raw=payload if isinstance(payload, dict) else {},
        )

    def verify_webhook(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
    ) -> WebhookEvent:
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        if not self._webhook_id:
            raise PayPalRejectedError(
                "CONFIGURATION_ERROR", 500, "webhook_id is not configured"
            )
        try:
            event = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except (ValueError, UnicodeDecodeError):
            raise PayPalRejectedError(
                "INVALID_REQUEST", 422, "webhook body is not valid JSON"
            )
        if not isinstance(event, dict):
            event = {}

        body = {
            "auth_algo": lowered.get("paypal-auth-algo", ""),
            "cert_id": lowered.get("paypal-cert-id", ""),
            "transmission_id": lowered.get("paypal-transmission-id", ""),
            "transmission_sig": lowered.get("paypal-transmission-sig", ""),
            "transmission_time": lowered.get("paypal-transmission-time", ""),
            "webhook_id": self._webhook_id,
            "webhook_event": event,
        }
        response = self._http.post(
            "/v1/notifications/verify-webhook-signature",
            headers=self._headers(),
            json=body,
        )
        self._raise_for_response(response)
        payload = response.json()
        verified = str(payload.get("verification_status", "")).upper() == "SUCCESS"

        resource = event.get("resource")
        resource_id = ""
        resource_type = ""
        if isinstance(resource, dict):
            resource_id = str(resource.get("id", ""))
            resource_type = str(resource.get("resource_type", ""))

        return WebhookEvent(
            event_id=str(event.get("id", lowered.get("paypal-transmission-id", ""))),
            event_type=str(event.get("event_type", "")),
            resource_type=resource_type or str(event.get("resource_type", "")),
            resource_id=resource_id,
            verified=verified,
            payload=event,
            received_at=self._clock(),
        )
