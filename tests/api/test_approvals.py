"""Approval-queue resolution and the unconfirmed-refund reconciliation path."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api import db as db_module
from backend.api import service
from backend.api.app import create_app
from backend.paypal.fake import FakePayPalGateway
from contracts import Capture, GatewayTimeout, Order, OrderItem

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


class AlwaysTimeoutGateway:
    """A gateway whose refund call always times out."""

    def refund_capture(self, *args, **kwargs):
        raise GatewayTimeout("GATEWAY_TIMEOUT", 504, "always times out")


def build_fake(amount_minor=5000):
    gateway = FakePayPalGateway(webhook_secret="whsec")
    capture = Capture(
        capture_id="CAP-1",
        order_id="ORDER-1",
        status="COMPLETED",
        amount_minor=amount_minor,
        currency="USD",
        refunded_amount_minor=0,
        created_at=NOW,
    )
    gateway.add_order(
        Order(
            order_id="ORDER-1",
            status="COMPLETED",
            amount_minor=amount_minor,
            currency="USD",
            created_at=NOW,
            payer_email="buyer@example.com",
            captures=(capture,),
            items=(OrderItem(name="Kopi mug", quantity=1, unit_amount_minor=amount_minor),),
        )
    )
    return gateway


def make_client(tmp_path, fake, per_refund=1000):
    app = create_app(
        str(tmp_path / "settle.db"),
        fake,
        token_secret="test-secret",
        now_fn=lambda: NOW,
    )
    client = TestClient(app)
    response = client.post(
        "/api/merchants",
        json={
            "name": "Kopi & Clay",
            "email": "shop@example.com",
            "currency": "USD",
            "per_refund_max_minor": per_refund,
            "daily_total_max_minor": 50000,
            "max_order_age_days": 90,
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["merchant_id"]


def classify(client, merchant_id):
    token = client.post(
        "/api/orders/ORDER-1/resolve-link", params={"merchant_id": merchant_id}
    ).json()["token"]
    body = client.post(
        "/api/resolve/%s" % token, json={"text": "The mug arrived broken."}
    ).json()
    return token, body


def test_cap_breach_approval_can_be_approved(tmp_path):
    fake = build_fake()
    client, merchant_id = make_client(tmp_path, fake, per_refund=1000)
    token, body = classify(client, merchant_id)

    assert body["decision"]["needs_approval"] is True
    assert body["decision"]["amount_minor"] == 1000

    accepted = client.post(
        "/api/resolve/%s/accept" % token, json={"case_id": body["case_id"]}
    ).json()
    assert accepted["status"] == "needs_approval"
    assert fake.get_capture("CAP-1").refunded_amount_minor == 0

    approvals = client.get(
        "/api/merchants/%s/approvals" % merchant_id
    ).json()["approvals"]
    assert len(approvals) == 1
    approval_id = approvals[0]["id"]

    approved = client.post(
        "/api/merchants/%s/approvals/%s/approve" % (merchant_id, approval_id)
    )
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert result["status"] == "refunded"
    assert result["amount_minor"] == 1000
    assert fake.get_capture("CAP-1").refunded_amount_minor == 1000

    detail = client.get(
        "/api/merchants/%s/cases/%s" % (merchant_id, body["case_id"])
    ).json()
    assert len(detail["audit_trail"]) == 1
    assert detail["audit_trail"][0]["rule_id"] == "damaged-or-not-as-described"

    approvals = client.get(
        "/api/merchants/%s/approvals" % merchant_id
    ).json()["approvals"]
    assert approvals[0]["status"] == "approved"


def test_approving_twice_does_not_double_refund(tmp_path):
    fake = build_fake()
    client, merchant_id = make_client(tmp_path, fake, per_refund=1000)
    token, body = classify(client, merchant_id)
    client.post(
        "/api/resolve/%s/accept" % token, json={"case_id": body["case_id"]}
    )
    approval_id = client.get(
        "/api/merchants/%s/approvals" % merchant_id
    ).json()["approvals"][0]["id"]

    client.post(
        "/api/merchants/%s/approvals/%s/approve" % (merchant_id, approval_id)
    )
    again = client.post(
        "/api/merchants/%s/approvals/%s/approve" % (merchant_id, approval_id)
    ).json()
    assert again["status"] == "approved"
    assert fake.get_capture("CAP-1").refunded_amount_minor == 1000


def test_reject_moves_no_money(tmp_path):
    fake = build_fake()
    client, merchant_id = make_client(tmp_path, fake, per_refund=1000)
    token, body = classify(client, merchant_id)
    client.post(
        "/api/resolve/%s/accept" % token, json={"case_id": body["case_id"]}
    )
    approval_id = client.get(
        "/api/merchants/%s/approvals" % merchant_id
    ).json()["approvals"][0]["id"]

    rejected = client.post(
        "/api/merchants/%s/approvals/%s/reject" % (merchant_id, approval_id)
    ).json()
    assert rejected["status"] == "rejected"
    assert fake.get_capture("CAP-1").refunded_amount_minor == 0


def test_unknown_approval_is_400(tmp_path):
    fake = build_fake()
    client, merchant_id = make_client(tmp_path, fake)
    response = client.post(
        "/api/merchants/%s/approvals/999/approve" % merchant_id
    )
    assert response.status_code == 400


def test_double_timeout_records_unconfirmed_then_reconciles(tmp_path):
    fake = build_fake()
    client, merchant_id = make_client(tmp_path, fake, per_refund=5000)
    _token, body = classify(client, merchant_id)

    connection = db_module.connect(str(tmp_path / "settle.db"))
    try:
        case_row = service.get_case_row(connection, body["case_id"])
        decision_row = service.get_latest_decision(connection, body["case_id"])

        first = service.execute_refund(
            connection,
            AlwaysTimeoutGateway(),
            merchant_id,
            case_row,
            decision_row,
            NOW,
        )
        assert first["status"] == "unconfirmed"
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM unconfirmed_refunds"
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
            == 0
        )

        # Reconcile against a healthy gateway using the same idempotency key.
        second = service.execute_refund(
            connection, fake, merchant_id, case_row, decision_row, NOW
        )
        assert second["status"] == "refunded"
        assert (
            connection.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS n FROM unconfirmed_refunds"
            ).fetchone()["n"]
            == 0
        )
        assert fake.get_capture("CAP-1").refunded_amount_minor == 5000
    finally:
        connection.close()
