"""Deterministic demo data for "Kopi & Clay".

Shared by the seeder and the server so that a resolve link printed by the
seeder points at an order the server also knows about.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from contracts import Caps, Capture, Dispute, Order, OrderItem

from backend.api import service
from backend.paypal.fake import FakePayPalGateway

DEMO_MERCHANT_ID = "m_kopiclay"
DEMO_WEBHOOK_SECRET = "dev-webhook-secret"
ORDER_COUNT = 25

DEMO_CAPS = Caps(
    per_refund_max_minor=5000,
    daily_total_max_minor=20000,
    max_order_age_days=90,
    currency="USD",
)

MENU = [
    ("Kopi mug", 2800),
    ("Clay cup", 3200),
    ("Pour-over set", 8900),
    ("Espresso cup", 2400),
    ("Kopi saucer", 1800),
]


def demo_order_specs(now: datetime = None) -> List[Dict[str, Any]]:
    reference = now or datetime.now(timezone.utc)
    specs: List[Dict[str, Any]] = []
    for index in range(ORDER_COUNT):
        name, unit = MENU[index % len(MENU)]
        quantity = 1 + (index % 2)
        specs.append(
            {
                "order_id": "ORDER-%03d" % (index + 1),
                "capture_id": "CAP-%03d" % (index + 1),
                "name": name,
                "quantity": quantity,
                "unit_amount_minor": unit,
                "amount_minor": unit * quantity,
                "created_at": reference - timedelta(days=(index * 3) % 40),
                "payer_email": "buyer%02d@example.com" % (index + 1),
            }
        )
    return specs


def build_demo_gateway(now: datetime = None) -> FakePayPalGateway:
    reference = now or datetime.now(timezone.utc)
    gateway = FakePayPalGateway(webhook_secret=DEMO_WEBHOOK_SECRET)
    for spec in demo_order_specs(reference):
        capture = Capture(
            capture_id=spec["capture_id"],
            order_id=spec["order_id"],
            status="COMPLETED",
            amount_minor=spec["amount_minor"],
            currency="USD",
            refunded_amount_minor=0,
            created_at=spec["created_at"],
        )
        order = Order(
            order_id=spec["order_id"],
            status="COMPLETED",
            amount_minor=spec["amount_minor"],
            currency="USD",
            created_at=spec["created_at"],
            payer_email=spec["payer_email"],
            captures=(capture,),
            items=(
                OrderItem(
                    name=spec["name"],
                    quantity=spec["quantity"],
                    unit_amount_minor=spec["unit_amount_minor"],
                ),
            ),
        )
        gateway.add_order(order)

    gateway.add_dispute(
        Dispute(
            dispute_id="DISPUTE-001",
            status="OPEN",
            reason="ITEM_NOT_RECEIVED",
            amount_minor=2800,
            currency="USD",
            created_at=reference,
            order_id="ORDER-001",
            capture_id="CAP-001",
            evidence_due_by=None,
        )
    )
    return gateway


def ensure_demo_merchant(connection, now: datetime) -> str:
    """Create the demo merchant once, with caps and an approved policy."""
    row = connection.execute(
        "SELECT id FROM merchants WHERE id = ?", (DEMO_MERCHANT_ID,)
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO merchants (id, name, email, created_at) VALUES (?, ?, ?, ?)",
            (
                DEMO_MERCHANT_ID,
                "Kopi & Clay",
                "shop@kopiandclay.example",
                service.iso(now),
            ),
        )
        connection.commit()

    service.set_caps(connection, DEMO_MERCHANT_ID, DEMO_CAPS)

    status = service.policy_status(connection, DEMO_MERCHANT_ID)
    if status.get("provider") is None:
        rules = service.active_rules(connection, DEMO_MERCHANT_ID)
        service.store_policy(
            connection,
            DEMO_MERCHANT_ID,
            rules,
            "defaults",
            "default-policy-v1",
            0,
            now,
        )
        service.approve_policy(connection, DEMO_MERCHANT_ID, now)

    return DEMO_MERCHANT_ID
