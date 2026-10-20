"""Human approval of queued refunds.

A ``needs_approval`` decision is a dead end unless a person can act on it.
Approving re-checks the **live** caps, so an approval can never refund more
than the current per-refund, remaining-refundable, or remaining-daily budget.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from contracts import GatewayTimeout, PolicyError

from . import service

__all__ = ["approve_refund", "reject_approval"]


def _ceiling(conn, merchant_id: str, capture, caps, now: datetime) -> int:
    remaining = capture.amount_minor - capture.refunded_amount_minor
    if remaining < 0:
        remaining = 0
    daily = (
        caps.daily_total_max_minor
        - service.today_history(conn, merchant_id, now).today_total_minor
    )
    if daily < 0:
        daily = 0
    return max(0, min(remaining, caps.per_refund_max_minor, daily))


def approve_refund(
    conn, gateway, merchant_id: str, approval_id: int, now: datetime
) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM approvals WHERE id = ? AND merchant_id = ?",
        (int(approval_id), merchant_id),
    ).fetchone()
    if row is None:
        raise PolicyError("approval %s not found" % (approval_id,))

    if row["status"] != "pending":
        return {
            "status": row["status"],
            "approval_id": int(row["id"]),
            "case_id": row["case_id"],
        }

    case_row = service.get_case_row(conn, row["case_id"])
    decision_row = service.get_latest_decision(conn, row["case_id"])
    caps = service.get_caps(conn, merchant_id)
    capture = gateway.get_capture(case_row["capture_id"])

    requested = int(row["amount_minor"])
    ceiling = _ceiling(conn, merchant_id, capture, caps, now)
    amount = min(requested, ceiling)
    if amount <= 0:
        return {
            "status": "blocked",
            "approval_id": int(row["id"]),
            "case_id": row["case_id"],
            "reason": "no budget remains under the current caps",
            "requested_amount_minor": requested,
            "ceiling_minor": ceiling,
        }

    idempotency_key = "settle-refund-%s" % (row["case_id"],)

    existing = conn.execute(
        "SELECT * FROM audit WHERE case_id = ? ORDER BY id DESC LIMIT 1",
        (row["case_id"],),
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE approvals SET status = 'approved' WHERE id = ?",
            (int(row["id"]),),
        )
        conn.commit()
        return {
            "status": "already_refunded",
            "approval_id": int(row["id"]),
            "case_id": row["case_id"],
            "refund_id": existing["refund_id"],
            "amount_minor": int(existing["amount_minor"]),
            "currency": existing["currency"],
        }

    try:
        refund = gateway.refund_capture(
            case_row["capture_id"], amount, row["currency"], idempotency_key
        )
    except GatewayTimeout:
        try:
            refund = gateway.refund_capture(
                case_row["capture_id"], amount, row["currency"], idempotency_key
            )
        except GatewayTimeout:
            service.record_unconfirmed(
                conn,
                merchant_id,
                row["case_id"],
                idempotency_key,
                amount,
                row["currency"],
                decision_row["rule_id"],
                now,
            )
            conn.execute(
                "UPDATE approvals SET status = 'approved' WHERE id = ?",
                (int(row["id"]),),
            )
            conn.commit()
            service.set_case_status(conn, row["case_id"], "unconfirmed")
            return {
                "status": "unconfirmed",
                "approval_id": int(row["id"]),
                "case_id": row["case_id"],
                "idempotency_key": idempotency_key,
                "amount_minor": amount,
                "currency": row["currency"],
            }

    service.record_audit(
        conn, merchant_id, case_row, decision_row, refund, idempotency_key, now
    )
    conn.execute(
        "UPDATE approvals SET status = 'approved' WHERE id = ?", (int(row["id"]),)
    )
    conn.commit()
    service.set_case_status(conn, row["case_id"], "refunded")

    return {
        "status": "refunded",
        "approval_id": int(row["id"]),
        "case_id": row["case_id"],
        "refund_id": refund.refund_id,
        "amount_minor": int(refund.amount_minor),
        "currency": refund.currency,
        "rule_id": decision_row["rule_id"],
    }


def reject_approval(conn, merchant_id: str, approval_id: int) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM approvals WHERE id = ? AND merchant_id = ?",
        (int(approval_id), merchant_id),
    ).fetchone()
    if row is None:
        raise PolicyError("approval %s not found" % (approval_id,))

    conn.execute(
        "UPDATE approvals SET status = 'rejected' WHERE id = ?", (int(row["id"]),)
    )
    conn.commit()
    service.set_case_status(conn, row["case_id"], "declined")
    return {
        "status": "rejected",
        "approval_id": int(row["id"]),
        "case_id": row["case_id"],
    }
