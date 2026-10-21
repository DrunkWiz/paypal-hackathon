"""The demo wiring a stranger actually runs: build_demo_app + seeded orders.

The other API tests construct their own gateway. This one exercises
`backend.api.server.build_demo_app`, which is what `python -m backend.api.server`
uses, so a break in the seeder/server handshake fails here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.server import build_demo_app
from backend.demo import DEMO_MERCHANT_ID, ORDER_COUNT


def test_demo_app_boots_with_fake_paypal_and_seeded_merchant(tmp_path):
    app = build_demo_app(str(tmp_path / "demo.db"))
    client = TestClient(app)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["paypal_mode"] == "fake"
    assert health["model_rungs_configured"] == 1

    merchant = client.get("/api/merchants/%s" % DEMO_MERCHANT_ID)
    assert merchant.status_code == 200, merchant.text
    body = merchant.json()
    assert body["merchant"]["name"] == "Kopi & Clay"
    assert body["policy"]["approved"] == 1
    assert body["caps"]["per_refund_max_minor"] == 5000


def test_demo_gateway_holds_every_seeded_order_and_the_dispute(tmp_path):
    app = build_demo_app(str(tmp_path / "demo.db"))
    gateway = app.state.gateway

    for index in range(ORDER_COUNT):
        order = gateway.get_order("ORDER-%03d" % (index + 1))
        assert order.captures[0].capture_id == "CAP-%03d" % (index + 1)

    disputes = gateway.list_disputes()
    assert [dispute.dispute_id for dispute in disputes] == ["DISPUTE-001"]


def test_seeded_order_can_be_resolved_end_to_end(tmp_path):
    app = build_demo_app(str(tmp_path / "demo.db"))
    client = TestClient(app)

    token = client.post(
        "/api/orders/ORDER-001/resolve-link",
        params={"merchant_id": DEMO_MERCHANT_ID},
    ).json()["token"]

    session = client.get("/api/resolve/%s" % token)
    assert session.status_code == 200, session.text
    assert session.json()["order_id"] == "ORDER-001"

    classified = client.post(
        "/api/resolve/%s" % token, json={"text": "The mug arrived broken."}
    )
    assert classified.status_code == 200, classified.text
    body = classified.json()
    assert body["category"] == "damaged"
    assert 0 < body["decision"]["amount_minor"] <= 5000

    accepted = client.post(
        "/api/resolve/%s/accept" % token, json={"case_id": body["case_id"]}
    ).json()
    assert accepted["status"] == "refunded"
    assert accepted["amount_minor"] == body["decision"]["amount_minor"]


def test_demo_app_honors_optional_live_credentials_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("SETTLE_ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("SETTLE_PAYPAL_CLIENT_ID", "pp-client-id")
    monkeypatch.setenv("SETTLE_PAYPAL_CLIENT_SECRET", "pp-client-secret")

    app = build_demo_app(str(tmp_path / "live_cfg.db"))
    client = TestClient(app)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["paypal_mode"] == "live"
    assert health["model_rungs_configured"] == 2

