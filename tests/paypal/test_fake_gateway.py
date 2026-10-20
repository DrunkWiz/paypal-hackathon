"""Behavioural tests for the deterministic fake gateway."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backend.paypal import FakePayPalGateway
from contracts import (
    Capture,
    Dispute,
    GatewayTimeout,
    NotFoundError,
    Order,
    OrderItem,
    PayPalRejectedError,
    PayPalTransientError,
)

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def seeded() -> FakePayPalGateway:
    gateway = FakePayPalGateway(webhook_secret="s3cret")
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
            items=(OrderItem(name="Kopi mug", quantity=1, unit_amount_minor=5000),),
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


def test_partial_refund_reduces_refundable_balance():
    gateway = seeded()
    gateway.refund_capture("CAP-1", 1200, "USD", "key-1")
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_partial_refunds_accumulate():
    gateway = seeded()
    gateway.refund_capture("CAP-1", 1200, "USD", "key-1")
    gateway.refund_capture("CAP-1", 800, "USD", "key-2")
    capture = gateway.get_capture("CAP-1")
    assert capture.refunded_amount_minor == 2000
    assert capture.amount_minor - capture.refunded_amount_minor == 3000


def test_over_refund_is_rejected():
    gateway = seeded()
    with pytest.raises(PayPalRejectedError) as excinfo:
        gateway.refund_capture("CAP-1", 6000, "USD", "key-1")
    assert excinfo.value.status == 422
    assert excinfo.value.code == "REFUND_EXCEEDS_CAPTURE"


def test_refund_beyond_remaining_after_partial_is_rejected():
    gateway = seeded()
    gateway.refund_capture("CAP-1", 4000, "USD", "key-1")
    with pytest.raises(PayPalRejectedError):
        gateway.refund_capture("CAP-1", 2000, "USD", "key-2")


def test_zero_refund_is_rejected():
    gateway = seeded()
    with pytest.raises(PayPalRejectedError):
        gateway.refund_capture("CAP-1", 0, "USD", "key-1")


def test_currency_mismatch_is_rejected():
    gateway = seeded()
    with pytest.raises(PayPalRejectedError):
        gateway.refund_capture("CAP-1", 100, "EUR", "key-1")


def test_idempotency_replay_returns_same_refund():
    gateway = seeded()
    first = gateway.refund_capture("CAP-1", 1200, "USD", "same-key")
    second = gateway.refund_capture("CAP-1", 1200, "USD", "same-key")
    assert first.refund_id == second.refund_id
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_idempotency_replay_wins_over_different_amount():
    gateway = seeded()
    first = gateway.refund_capture("CAP-1", 1200, "USD", "same-key")
    second = gateway.refund_capture("CAP-1", 9999, "USD", "same-key")
    assert second.refund_id == first.refund_id
    assert second.amount_minor == 1200
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_timeout_after_accept_leaves_exactly_one_refund():
    gateway = seeded()
    gateway.inject_fault("refund_capture", "timeout_after_accept")
    with pytest.raises(GatewayTimeout):
        gateway.refund_capture("CAP-1", 1200, "USD", "retry-key")
    # The refund exists even though the caller saw a timeout.
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200
    # The retry returns the original refund and does not refund twice.
    replay = gateway.refund_capture("CAP-1", 1200, "USD", "retry-key")
    assert replay.amount_minor == 1200
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 1200


def test_timeout_before_accept_does_not_move_money():
    gateway = seeded()
    gateway.inject_fault("refund_capture", "timeout")
    with pytest.raises(GatewayTimeout):
        gateway.refund_capture("CAP-1", 1200, "USD", "key-1")
    assert gateway.get_capture("CAP-1").refunded_amount_minor == 0


def test_injected_5xx_is_transient():
    gateway = seeded()
    gateway.inject_fault("get_order", "5xx")
    with pytest.raises(PayPalTransientError):
        gateway.get_order("ORDER-1")


def test_injected_422_is_rejected():
    gateway = seeded()
    gateway.inject_fault("get_order", "422")
    with pytest.raises(PayPalRejectedError):
        gateway.get_order("ORDER-1")


def test_unknown_order_raises_not_found():
    gateway = seeded()
    with pytest.raises(NotFoundError):
        gateway.get_order("NOPE")


def test_unknown_capture_raises_not_found():
    gateway = seeded()
    with pytest.raises(NotFoundError):
        gateway.get_capture("NOPE")


def test_list_disputes():
    gateway = seeded()
    disputes = gateway.list_disputes()
    assert [dispute.dispute_id for dispute in disputes] == ["DISPUTE-1"]


def test_get_dispute():
    gateway = seeded()
    dispute = gateway.get_dispute("DISPUTE-1")
    assert dispute.reason == "ITEM_NOT_RECEIVED"


def test_webhook_verifies_with_correct_signature():
    gateway = seeded()
    payload = {
        "id": "WH-1",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {"id": "REFUND-1", "resource_type": "refund"},
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = gateway.sign_webhook(raw)
    event = gateway.verify_webhook(
        {"paypal-transmission-sig": signature, "paypal-transmission-id": "WH-1"}, raw
    )
    assert event.verified is True
    assert event.event_id == "WH-1"
    assert event.resource_id == "REFUND-1"


def test_webhook_rejects_bad_signature():
    gateway = seeded()
    payload = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.REFUNDED"}
    raw = json.dumps(payload).encode("utf-8")
    event = gateway.verify_webhook({"paypal-transmission-sig": "deadbeef"}, raw)
    assert event.verified is False
