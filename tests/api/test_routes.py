"""Route-level tests: onboarding, policy, caps, health, webhook, dashboard reads."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.paypal.fake import FakePayPalGateway
from contracts import Capture, Dispute, Order, OrderItem

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def build_fake():
    gateway = FakePayPalGateway(webhook_secret="whsec")
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


@pytest.fixture
def client(tmp_path):
    app = create_app(
        str(tmp_path / "settle.db"),
        build_fake(),
        token_secret="test-secret",
        now_fn=lambda: NOW,
    )
    return TestClient(app)


@pytest.fixture
def merchant(client):
    response = client.post(
        "/api/merchants",
        json={
            "name": "Kopi & Clay",
            "email": "shop@example.com",
            "currency": "USD",
            "per_refund_max_minor": 5000,
            "daily_total_max_minor": 20000,
            "max_order_age_days": 90,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["merchant_id"]


def test_onboarding_returns_merchant_and_caps(client):
    response = client.post(
        "/api/merchants",
        json={"name": "A", "email": "a@example.com", "currency": "SGD"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"].startswith("m_")
    assert body["caps"]["currency"] == "SGD"


def test_get_merchant(client, merchant):
    response = client.get("/api/merchants/%s" % merchant)
    assert response.status_code == 200
    body = response.json()
    assert body["merchant"]["name"] == "Kopi & Clay"
    assert body["policy"]["approved"] is False


def test_get_and_put_caps(client, merchant):
    response = client.get("/api/merchants/%s/caps" % merchant)
    assert response.json()["per_refund_max_minor"] == 5000

    updated = client.put(
        "/api/merchants/%s/caps" % merchant,
        json={
            "per_refund_max_minor": 2500,
            "daily_total_max_minor": 10000,
            "max_order_age_days": 30,
            "currency": "USD",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["per_refund_max_minor"] == 2500


def test_policy_compile_and_approve(client, merchant):
    compiled = client.post(
        "/api/merchants/%s/policy/compile" % merchant,
        json={"text": "Full refunds for damaged items."},
    )
    assert compiled.status_code == 200
    body = compiled.json()
    assert body["provider"] == "fake"
    assert body["approved"] is False
    assert len(body["rules"]) >= 1

    approved = client.post("/api/merchants/%s/policy/approve" % merchant)
    assert approved.json()["approved"] is True

    policy = client.get("/api/merchants/%s/policy" % merchant)
    assert policy.json()["status"]["approved"] == 1


def test_health_reports_fake_mode_and_rung(client, merchant):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["paypal_mode"] == "fake"
    assert health.json()["model_rungs_configured"] == 1

    client.post(
        "/api/merchants/%s/policy/compile" % merchant,
        json={"text": "Anything."},
    )
    health = client.get("/api/health").json()
    assert health["model_provider"] == "fake"
    assert health["model_rung"] == 0


def test_unknown_merchant_is_404(client):
    assert client.get("/api/merchants/nope").status_code == 404


def test_disputes_read(client, merchant):
    response = client.get("/api/merchants/%s/disputes" % merchant)
    assert response.status_code == 200
    disputes = response.json()["disputes"]
    assert disputes[0]["dispute_id"] == "DISPUTE-1"
    assert disputes[0]["amount_minor"] == 5000


def test_totals_start_at_zero(client, merchant):
    totals = client.get("/api/merchants/%s/totals" % merchant).json()
    assert totals["refunded_all_time_minor"] == 0
    assert totals["refund_count"] == 0
    assert totals["pending_approvals"] == 0


def test_cases_list_starts_empty(client, merchant):
    assert client.get("/api/merchants/%s/cases" % merchant).json()["cases"] == []


def test_orders_read(client, merchant):
    response = client.get("/api/merchants/%s/orders" % merchant)
    assert response.status_code == 200
    orders = response.json()["orders"]
    assert len(orders) == 1
    assert orders[0]["order_id"] == "ORDER-1"
    assert orders[0]["amount_minor"] == 5000
    assert orders[0]["capture"]["capture_id"] == "CAP-1"
    assert orders[0]["items"][0]["name"] == "Kopi mug"



def test_webhook_accepts_valid_signature(client):
    app_fake = build_fake()
    payload = {
        "id": "WH-1",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "resource": {"id": "REFUND-1", "resource_type": "refund"},
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = app_fake.sign_webhook(raw)

    response = client.post(
        "/api/webhooks/paypal",
        content=raw,
        headers={
            "paypal-transmission-sig": signature,
            "paypal-transmission-id": "WH-1",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["event_id"] == "WH-1"


def test_webhook_rejects_bad_signature(client):
    raw = json.dumps({"id": "WH-2", "event_type": "X"}).encode("utf-8")
    response = client.post(
        "/api/webhooks/paypal",
        content=raw,
        headers={"paypal-transmission-sig": "bogus"},
    )
    assert response.status_code == 400
