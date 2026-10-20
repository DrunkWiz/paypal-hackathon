from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, List, Mapping, Optional, Tuple
from typing import Protocol
from typing import runtime_checkable


class DisputeAction(str, Enum):
    provide_evidence = "provide_evidence"
    accept_claim = "accept_claim"
    make_offer = "make_offer"


@dataclass(frozen=True)
class OrderItem:
    name: str
    quantity: int
    unit_amount_minor: int


@dataclass(frozen=True)
class Capture:
    capture_id: str
    order_id: str
    status: str
    amount_minor: int
    currency: str
    refunded_amount_minor: int
    created_at: datetime


@dataclass(frozen=True)
class Order:
    order_id: str
    status: str
    amount_minor: int
    currency: str
    created_at: datetime
    payer_email: str
    captures: Tuple[Capture, ...]
    items: Tuple[OrderItem, ...]


@dataclass(frozen=True)
class Refund:
    refund_id: str
    capture_id: str
    status: str
    amount_minor: int
    currency: str
    created_at: datetime


@dataclass(frozen=True)
class Dispute:
    dispute_id: str
    status: str
    reason: str
    amount_minor: int
    currency: str
    created_at: datetime
    order_id: Optional[str]
    capture_id: Optional[str]
    evidence_due_by: Optional[datetime]


@dataclass(frozen=True)
class DisputeActionResult:
    dispute_id: str
    action: DisputeAction
    status: str
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    event_type: str
    resource_type: str
    resource_id: str
    verified: bool
    payload: Mapping[str, Any]
    received_at: datetime


@runtime_checkable
class PayPalGateway(Protocol):
    def get_order(self, order_id: str) -> Order: ...
    def get_capture(self, capture_id: str) -> Capture: ...
    def refund_capture(
        self,
        capture_id: str,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
    ) -> Refund: ...
    def list_disputes(self) -> List[Dispute]: ...
    def get_dispute(self, dispute_id: str) -> Dispute: ...
    def provide_dispute_evidence(
        self,
        dispute_id: str,
        evidence: Mapping[str, Any],
        idempotency_key: str,
    ) -> DisputeActionResult: ...
    def accept_dispute_claim(
        self,
        dispute_id: str,
        idempotency_key: str,
    ) -> DisputeActionResult: ...
    def verify_webhook(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
    ) -> WebhookEvent: ...