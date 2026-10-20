"""One contract suite, two implementations.

``fake`` is the in-memory gateway. ``client`` is the real httpx client talking
to a faithful PayPal-shaped mock transport backed by the same fake. If these
two disagree, the real client has a parsing or error-mapping bug.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typing import Any, Dict

from backend.paypal import FakePayPalGateway, PayPalClient
from backend.paypal.testing import make_gateway_transport
from contracts import (
    Capture,
    Dispute,
    DisputeAction,
    NotFoundError,
    Order,
    OrderItem,
    PayPalGateway,
    PayPalRejectedError,
)

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def seeded_fake(webhook_secret: str = "s3cret") -> FakePayPalGateway:
    gateway = FakePayPalGateway(webhook_secret=webhook_secret)
    capture = Capture(
        capture_id="CAP-1",
        order_id="ORDER-1",
        status="COMPLETED",
        amount_minor=5000,
        currency="USD",
        refunded_amount_minor=0,
        created_at=NOW,
    )
    gateway.add_order(
        Order(
            order_id="ORDER-1",
            status="COMPLETED",
            amount_minor=5000,
            currency="USD",
            created_at=NOW,
            payer_email="buyer@example.com",
            captures=(capture,),
            items=(OrderItem(name="Kopi mug", quantity=2, unit_amount_minor=2500),),
        )
    )
    gateway.add_dispute(
        Dispute(
            dispute_id="DISPUTE-1",
            status="OPEN",
            reason="ITEM_NOT_RECEIVED",
            amount_minor=5000,
            currency="USD",
            created_at=NOW,
            order_id="ORDER-1",
            capture_id="CAP-1",
            evidence_due_by=None,
        )
    )
    return gateway


@pytest.fixture(params=["fake", "client"])
def pair(request):
    fake = seeded_fake()
    if request.param == "fake":
        yield (fake, fake)
        return
    client = PayPalClient(
        "client-id",
        "client-secret",
        transport=make_gateway_transport(fake),
        webhook_id="WH-ID",
        clock=lambda: NOW,
    )
    try:
        yield (client, fake)
    finally:
        client.close()


def test_both_satisfy_the_protocol(pair):
    gateway, _ = pair
    assert isinstance(gateway, PayPalGateway) is True


def test_get_order(pair):
    gateway, _ = pair
    order = gateway.get_order("ORDER-1")
    assert order.order_id == "ORDER-1"
    assert order.status == "COMPLETED"
    assert order.amount_minor == 5000
    assert order.currency == "USD"
    assert order.payer_email == "buyer@example.com"
    assert len(order.captures) == 1
    assert order.items[0].name == "Kopi mug"


def test_get_capture(pair):
    gateway, _ = pair
    capture = gateway.get_capture("CAP-1")
    assert capture.capture_id == "CAP-1"
    assert capture.amount_minor == 5000
    assert capture.refunded_amount_minor == 0


def test_refund_reduces_balance(pair):
    gateway, _ = pair
    refund = gateway.refund_capture("CAP-1", 1200, "USD", "key-1")
    assert refund.amount_minor == 1200
    assert refund.currency == "USD"
    assert refund.capture_id == "CAP-1"
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_over_refund_rejected(pair):
    gateway, _ = pair
    with pytest.raises(PayPalRejectedError):
        gateway.refund_capture("CAP-1", 6000, "USD", "key-1")


def test_idempotency_replay_same_refund(pair):
    gateway, _ = pair
    first = gateway.refund_capture("CAP-1", 1200, "USD", "replay-key")
    second = gateway.refund_capture("CAP-1", 1200, "USD", "replay-key")
    assert first.refund_id == second.refund_id
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_timeout_after_accept_then_retry_refunds_once(pair):
    gateway, fake = pair
    fake.inject_fault("refund_capture", "timeout_after_accept")
    with pytest.raises(Exception):
        gateway.refund_capture("CAP-1", 1200, "USD", "retry-key")
    replay = gateway.refund_capture("CAP-1", 1200, "USD", "retry-key")
    assert replay.amount_minor == 1200
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_missing_order_raises_not_found(pair):
    gateway, _ = pair
    with pytest.raises(NotFoundError):
        gateway.get_order("NOPE")


def test_list_disputes(pair):
    gateway, _ = pair
    disputes = gateway.list_disputes()
    assert [dispute.dispute_id for dispute in disputes] == ["DISPUTE-1"]


def test_get_dispute(pair):
    gateway, _ = pair
    dispute = gateway.get_dispute("DISPUTE-1")
    assert dispute.reason == "ITEM_NOT_RECEIVED"
    assert dispute.amount_minor == 5000


def test_provide_evidence(pair):
    gateway, _ = pair
    result = gateway.provide_dispute_evidence("DISPUTE-1", {"note": "shipped"}, "ev-1")
    assert result.dispute_id == "DISPUTE-1"
    assert result.action == DisputeAction.provide_evidence


def test_accept_claim(pair):
    gateway, _ = pair
    result = gateway.accept_dispute_claim("DISPUTE-1", "ac-1")
    assert result.dispute_id == "DISPUTE-1"
    assert result.action == DisputeAction.accept_claim


def test_webhook_verified(pair):
    gateway, fake = pair
    payload = {
        "id": "WH-1",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {"id": "REFUND-1", "resource_type": "refund"},
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = fake.sign_webhook(raw)
    event = gateway.verify_webhook(
        {
            "paypal-transmission-id": "WH-1",
            "paypal-transmission-sig": signature,
        },
        raw,
    )
    assert event.verified is True
    assert event.event_id == "WH-1"
    assert event.resource_id == "REFUND-1"


def test_webhook_unverified(pair):
    gateway, _ = pair
    raw = json.dumps({"id": "WH-2", "event_type": "X"}).encode("utf-8")
    event = gateway.verify_webhook({"paypal-transmission-sig": "bogus"}, raw)
    assert event.verified is False
