"""Deterministic in-memory PayPal gateway.

This is the only gateway that can be verified without credentials, so it must
behave like the real API in the ways that matter to money:

* partial refunds reduce the capture's refundable balance,
* an over-refund is rejected (422), not silently clamped,
* replaying an idempotency key returns the *same* refund and never refunds twice,
* a timeout after the gateway accepted the refund still leaves exactly one refund
  behind (``timeout_after_accept``),
* 5xx / timeout / 422 faults are injectable.

No network, no clock reads unless a clock is injected.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from contracts import (
    Capture,
    Dispute,
    DisputeAction,
    DisputeActionResult,
    GatewayTimeout,
    NotFoundError,
    Order,
    PayPalRejectedError,
    PayPalTransientError,
    Refund,
    WebhookEvent,
)

__all__ = ["FakePayPalGateway"]

_FAILURE_KINDS = ("timeout", "timeout_after_accept", "5xx", "422")

_EPOCH = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _default_clock() -> datetime:
    return _EPOCH


class FakePayPalGateway:
    """Implements the ``PayPalGateway`` protocol in memory."""

    def __init__(
        self,
        webhook_secret: str = "fake-webhook-secret",
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._orders: Dict[str, Order] = {}
        self._captures: Dict[str, Capture] = {}
        self._refunds: Dict[str, Refund] = {}
        self._disputes: Dict[str, Dispute] = {}
        self._idempotency: Dict[str, Refund] = {}
        self._counter = 0
        self._faults: List[Tuple[str, str]] = []
        self._webhook_secret = webhook_secret
        self._clock = clock or _default_clock

    # -- seeding ---------------------------------------------------------

    def add_order(self, order: Order) -> None:
        self._orders[order.order_id] = order
        for capture in order.captures:
            self._captures[capture.capture_id] = capture

    def add_dispute(self, dispute: Dispute) -> None:
        self._disputes[dispute.dispute_id] = dispute

    def inject_fault(self, operation: str, kind: str) -> None:
        """Queue a fault for the next call to ``operation``."""
        if kind not in _FAILURE_KINDS:
            raise ValueError("unknown fault kind %r" % (kind,))
        self._faults.append((operation, kind))

    def sign_webhook(self, raw_body: bytes) -> str:
        return hmac.new(
            self._webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()

    # -- internals -------------------------------------------------------

    def _take_fault(self, operation: str) -> Optional[str]:
        for index, (queued_operation, kind) in enumerate(self._faults):
            if queued_operation == operation:
                del self._faults[index]
                return kind
        return None

    @staticmethod
    def _raise_for(kind: str) -> None:
        if kind == "timeout":
            raise GatewayTimeout("GATEWAY_TIMEOUT", 504, "simulated gateway timeout")
        if kind == "5xx":
            raise PayPalTransientError(
                "INTERNAL_SERVER_ERROR", 500, "simulated upstream failure"
            )
        if kind == "422":
            raise PayPalRejectedError(
                "UNPROCESSABLE_ENTITY", 422, "simulated rejection"
            )

    def _current_capture(self, capture_id: str) -> Capture:
        capture = self._captures.get(capture_id)
        if capture is None:
            raise NotFoundError("capture %s not found" % (capture_id,))
        return capture

    def _current_order(self, order: Order) -> Order:
        captures = tuple(
            self._captures.get(capture.capture_id, capture)
            for capture in order.captures
        )
        return dataclasses.replace(order, captures=captures)

    # -- gateway protocol ------------------------------------------------

    def get_order(self, order_id: str) -> Order:
        kind = self._take_fault("get_order")
        if kind is not None:
            self._raise_for(kind)
        order = self._orders.get(order_id)
        if order is None:
            raise NotFoundError("order %s not found" % (order_id,))
        return self._current_order(order)

    def get_capture(self, capture_id: str) -> Capture:
        kind = self._take_fault("get_capture")
        if kind is not None:
            self._raise_for(kind)
        return self._current_capture(capture_id)

    def refund_capture(
        self,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> Refund:
        # Replay is checked before any fault: a caller who retried after a
        # timeout must get the original refund back, not a new one.
        if not idempotency_key:
            raise PayPalRejectedError(
                "INVALID_REQUEST", 422, "idempotency_key is required"
            )
        if idempotency_key in self._idempotency:
            return self._idempotency[idempotency_key]

        kind = self._take_fault("refund_capture")
        if kind is not None and kind != "timeout_after_accept":
            self._raise_for(kind)

        capture = self._current_capture(capture_id)
        if currency != capture.currency:
            raise PayPalRejectedError(
                "CURRENCY_MISMATCH",
                422,
                "capture currency %s != requested %s"
                % (capture.currency, currency),
            )
        if not isinstance(amount_minor, int) or isinstance(amount_minor, bool):
            raise PayPalRejectedError(
                "INVALID_REQUEST", 422, "amount must be integer minor units"
            )
        if amount_minor <= 0:
            raise PayPalRejectedError(
                "INVALID_REQUEST", 422, "amount must be positive"
            )

        remaining = capture.amount_minor - capture.refunded_amount_minor
        if amount_minor > remaining:
            raise PayPalRejectedError(
                "REFUND_EXCEEDS_CAPTURE",
                422,
                "refund %d exceeds remaining %d" % (amount_minor, remaining),
            )

        self._counter += 1
        refund = Refund(
            refund_id="REFUND-%04d" % self._counter,
            capture_id=capture_id,
            status="COMPLETED",
            amount_minor=amount_minor,
            currency=currency,
            created_at=self._clock(),
        )
        self._refunds[refund.refund_id] = refund
        self._captures[capture_id] = dataclasses.replace(
            capture,
            refunded_amount_minor=capture.refunded_amount_minor + amount_minor,
        )
        self._idempotency[idempotency_key] = refund

        if kind == "timeout_after_accept":
            # The refund exists; the caller just never hears about it.
            raise GatewayTimeout(
                "GATEWAY_TIMEOUT", 504, "simulated timeout after acceptance"
            )
        return refund

    def list_disputes(self) -> List[Dispute]:
        kind = self._take_fault("list_disputes")
        if kind is not None:
            self._raise_for(kind)
        return list(self._disputes.values())

    def get_dispute(self, dispute_id: str) -> Dispute:
        kind = self._take_fault("get_dispute")
        if kind is not None:
            self._raise_for(kind)
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            raise NotFoundError("dispute %s not found" % (dispute_id,))
        return dispute

    def provide_dispute_evidence(
        self,
        dispute_id: str,
        evidence: Mapping[str, Any],
        idempotency_key: str,
    ) -> DisputeActionResult:
        dispute = self.get_dispute(dispute_id)
        return DisputeActionResult(
            dispute_id=dispute.dispute_id,
            action=DisputeAction.provide_evidence,
            status="EVIDENCE_PROVIDED",
            raw={"evidence": dict(evidence), "idempotency_key": idempotency_key},
        )

    def accept_dispute_claim(
        self,
        dispute_id: str,
        idempotency_key: str,
    ) -> DisputeActionResult:
        dispute = self.get_dispute(dispute_id)
        return DisputeActionResult(
            dispute_id=dispute.dispute_id,
            action=DisputeAction.accept_claim,
            status="ACCEPTED",
            raw={"idempotency_key": idempotency_key},
        )

    def verify_webhook(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
    ) -> WebhookEvent:
        lowered = {str(key).lower(): str(value) for key, value in headers.items()}
        supplied = lowered.get("paypal-transmission-sig", "")
        expected = self.sign_webhook(raw_body)
        verified = hmac.compare_digest(supplied, expected)

        payload: Mapping[str, Any]
        try:
            decoded = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            payload = decoded if isinstance(decoded, dict) else {}
        except (ValueError, UnicodeDecodeError):
            payload = {}

        resource = payload.get("resource")
        resource_id = ""
        resource_type = ""
        if isinstance(resource, dict):
            resource_id = str(resource.get("id", ""))
            resource_type = str(resource.get("resource_type", ""))

        return WebhookEvent(
            event_id=str(payload.get("id", lowered.get("paypal-transmission-id", ""))),
            event_type=str(payload.get("event_type", "")),
            resource_type=resource_type or str(payload.get("resource_type", "")),
            resource_id=resource_id,
            verified=verified,
            payload=dict(payload),
            received_at=self._clock(),
        )
