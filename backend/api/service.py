"""Resolve and execution logic. Pure-ish: all I/O is an explicit connection."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from contracts import (
    Caps,
    Case,
    Decision,
    GatewayTimeout,
    History,
    Order,
    OrderSnapshot,
    PolicyError,
    Refund,
    Rule,
)

from backend.agent import default_policy, rule_to_json
from backend.agent.prompts import validate_rules
from backend.policy import evaluate

from .db import row_to_dict

__all__ = [
    "iso",
    "create_merchant",
    "set_caps",
    "get_caps",
    "store_policy",
    "approve_policy",
    "active_rules",
    "policy_status",
    "store_case",
    "store_decision",
    "get_case_row",
    "get_latest_decision",
    "set_case_status",
    "execute_refund",
    "record_unconfirmed",
    "clear_unconfirmed",
    "queue_approval",
    "today_history",
    "snapshot_from_order",
    "list_cases",
    "case_detail",
    "list_approvals",
    "totals",
]


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


# -- merchants and caps -----------------------------------------------------


def create_merchant(conn, name: str, email: str, caps: Caps, now: datetime) -> str:
    merchant_id = "m_" + uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO merchants (id, name, email, created_at) VALUES (?, ?, ?, ?)",
        (merchant_id, name, email, iso(now)),
    )
    set_caps(conn, merchant_id, caps)
    conn.commit()
    return merchant_id


def set_caps(conn, merchant_id: str, caps: Caps) -> None:
    conn.execute(
        "INSERT INTO caps "
        "(merchant_id, per_refund_max_minor, daily_total_max_minor, "
        " max_order_age_days, currency) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(merchant_id) DO UPDATE SET "
        " per_refund_max_minor=excluded.per_refund_max_minor, "
        " daily_total_max_minor=excluded.daily_total_max_minor, "
        " max_order_age_days=excluded.max_order_age_days, "
        " currency=excluded.currency",
        (
            merchant_id,
            int(caps.per_refund_max_minor),
            int(caps.daily_total_max_minor),
            int(caps.max_order_age_days),
            caps.currency,
        ),
    )
    conn.commit()


def get_caps(conn, merchant_id: str) -> Caps:
    row = conn.execute(
        "SELECT * FROM caps WHERE merchant_id = ?", (merchant_id,)
    ).fetchone()
    if row is None:
        raise PolicyError("merchant %s has no caps" % (merchant_id,))
    return Caps(
        per_refund_max_minor=int(row["per_refund_max_minor"]),
        daily_total_max_minor=int(row["daily_total_max_minor"]),
        max_order_age_days=int(row["max_order_age_days"]),
        currency=str(row["currency"]),
    )


# -- policy -----------------------------------------------------------------


def store_policy(
    conn,
    merchant_id: str,
    rules: List[Rule],
    provider: str,
    model: str,
    rung: int,
    now: datetime,
) -> int:
    payload = json.dumps([rule_to_json(rule) for rule in rules])
    cursor = conn.execute(
        "INSERT INTO policies "
        "(merchant_id, rules_json, provider, model, rung, approved, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (merchant_id, payload, provider, model, int(rung), iso(now)),
    )
    conn.commit()
    return int(cursor.lastrowid)


def approve_policy(conn, merchant_id: str, now: datetime) -> int:
    row = conn.execute(
        "SELECT id FROM policies WHERE merchant_id = ? ORDER BY id DESC LIMIT 1",
        (merchant_id,),
    ).fetchone()
    if row is None:
        raise PolicyError("merchant %s has no policy to approve" % (merchant_id,))
    policy_id = int(row["id"])
    conn.execute(
        "UPDATE policies SET approved = 1, approved_at = ? WHERE id = ?",
        (iso(now), policy_id),
    )
    conn.commit()
    return policy_id


def active_rules(conn, merchant_id: str) -> List[Rule]:
    row = conn.execute(
        "SELECT rules_json FROM policies "
        "WHERE merchant_id = ? AND approved = 1 ORDER BY id DESC LIMIT 1",
        (merchant_id,),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT rules_json FROM policies WHERE merchant_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (merchant_id,),
        ).fetchone()
    if row is None:
        return list(default_policy())
    return validate_rules({"rules": json.loads(row["rules_json"])})


def policy_status(conn, merchant_id: str) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT approved, provider, model, rung, created_at FROM policies "
        "WHERE merchant_id = ? ORDER BY id DESC LIMIT 1",
        (merchant_id,),
    ).fetchone()
    if row is None:
        return {
            "approved": False,
            "provider": None,
            "model": None,
            "rung": None,
            "created_at": None,
        }
    return row_to_dict(row)


# -- cases and decisions ----------------------------------------------------


def store_case(conn, merchant_id: str, case: Case, now: datetime) -> str:
    case_id = "c_" + uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO cases "
        "(id, merchant_id, order_id, capture_id, category, sentiment, wants, "
        " confidence, raw_text, facts_json, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            case_id,
            merchant_id,
            case.order_id,
            case.capture_id,
            case.category.value,
            case.sentiment.value,
            case.wants.value,
            float(case.confidence),
            case.raw_text,
            json.dumps(dict(case.facts)),
            "open",
            iso(now),
        ),
    )
    conn.commit()
    return case_id


def store_decision(conn, case_id: str, decision: Decision, now: datetime) -> None:
    conn.execute(
        "INSERT INTO decisions "
        "(case_id, action, amount_minor, currency, rule_id, reason, "
        " needs_approval, percent_applied, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            case_id,
            decision.action.value,
            int(decision.amount_minor),
            decision.currency,
            decision.rule_id,
            decision.reason,
            1 if decision.needs_approval else 0,
            decision.percent_applied,
            iso(now),
        ),
    )
    conn.commit()


def get_case_row(conn, case_id: str):
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise PolicyError("case %s not found" % (case_id,))
    return row


def get_latest_decision(conn, case_id: str):
    row = conn.execute(
        "SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    if row is None:
        raise PolicyError("case %s has no decision" % (case_id,))
    return row


def set_case_status(conn, case_id: str, status: str) -> None:
    conn.execute("UPDATE cases SET status = ? WHERE id = ?", (status, case_id))
    conn.commit()


# -- execution --------------------------------------------------------------


def record_unconfirmed(
    conn,
    merchant_id: str,
    case_id: str,
    idempotency_key: str,
    amount_minor: int,
    currency: str,
    rule_id,
    now: datetime,
) -> None:
    """Persist a refund attempt whose outcome the gateway never confirmed."""
    conn.execute(
        "INSERT INTO unconfirmed_refunds "
        "(merchant_id, case_id, idempotency_key, amount_minor, currency, "
        " rule_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(idempotency_key) DO UPDATE SET "
        " amount_minor=excluded.amount_minor",
        (
            merchant_id,
            case_id,
            idempotency_key,
            int(amount_minor),
            currency,
            rule_id,
            iso(now),
        ),
    )
    conn.commit()


def clear_unconfirmed(conn, idempotency_key: str) -> None:
    conn.execute(
        "DELETE FROM unconfirmed_refunds WHERE idempotency_key = ?",
        (idempotency_key,),
    )
    conn.commit()


def record_audit(
    conn,
    merchant_id: str,
    case_row,
    decision_row,
    refund,
    idempotency_key: str,
    now: datetime,
) -> None:
    """Write the audit row naming the rule that fired, and clear any unknown."""
    conn.execute(
        "INSERT INTO audit "
        "(merchant_id, case_id, order_id, capture_id, refund_id, amount_minor, "
        " currency, rule_id, idempotency_key, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            merchant_id,
            case_row["id"],
            case_row["order_id"],
            case_row["capture_id"],
            refund.refund_id,
            int(refund.amount_minor),
            refund.currency,
            decision_row["rule_id"],
            idempotency_key,
            iso(now),
        ),
    )
    conn.commit()
    clear_unconfirmed(conn, idempotency_key)


def queue_approval(conn, merchant_id: str, case_row, decision_row, now: datetime) -> None:
    conn.execute(
        "INSERT INTO approvals "
        "(merchant_id, case_id, amount_minor, currency, reason, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
        (
            merchant_id,
            case_row["id"],
            int(decision_row["amount_minor"]),
            decision_row["currency"],
            decision_row["reason"],
            iso(now),
        ),
    )
    conn.commit()


def execute_refund(
    conn, gateway, merchant_id: str, case_row, decision_row, now: datetime
) -> Dict[str, Any]:
    """Execute at most one refund per case, idempotently.

    The idempotency key is derived from the case id, so a timeout after the
    gateway accepted the refund still means exactly one refund on retry.
    """
    case_id = str(case_row["id"])
    amount_minor = int(decision_row["amount_minor"])

    if amount_minor <= 0 or int(decision_row["needs_approval"]) == 1:
        queue_approval(conn, merchant_id, case_row, decision_row, now)
        set_case_status(conn, case_id, "needs_approval")
        return {
            "status": "needs_approval",
            "case_id": case_id,
            "amount_minor": amount_minor,
            "currency": decision_row["currency"],
            "rule_id": decision_row["rule_id"],
        }

    existing = conn.execute(
        "SELECT * FROM audit WHERE case_id = ? ORDER BY id DESC LIMIT 1",
        (case_id,),
    ).fetchone()
    if existing is not None:
        return {
            "status": "already_refunded",
            "case_id": case_id,
            "refund_id": existing["refund_id"],
            "amount_minor": int(existing["amount_minor"]),
            "currency": existing["currency"],
            "rule_id": existing["rule_id"],
            "audit_id": int(existing["id"]),
        }

    idempotency_key = "settle-refund-%s" % (case_id,)
    currency = decision_row["currency"]

    try:
        refund = gateway.refund_capture(
            case_row["capture_id"], amount_minor, currency, idempotency_key
        )
    except GatewayTimeout:
        # The gateway may have accepted before the timeout. Retry with the same
        # key: it returns the original refund instead of creating a second one.
        try:
            refund = gateway.refund_capture(
                case_row["capture_id"], amount_minor, currency, idempotency_key
            )
        except GatewayTimeout:
            # Both calls timed out, so the outcome is genuinely unknown. Record
            # the attempt so money can never move silently, and let the next
            # attempt reconcile it with the same idempotency key.
            record_unconfirmed(
                conn,
                merchant_id,
                case_id,
                idempotency_key,
                amount_minor,
                currency,
                decision_row["rule_id"],
                now,
            )
            set_case_status(conn, case_id, "unconfirmed")
            return {
                "status": "unconfirmed",
                "case_id": case_id,
                "idempotency_key": idempotency_key,
                "amount_minor": amount_minor,
                "currency": currency,
                "rule_id": decision_row["rule_id"],
                "message": (
                    "The payment gateway timed out twice. The refund may have "
                    "been accepted. Accept again to reconcile; the idempotency "
                    "key guarantees at most one refund."
                ),
            }

    record_audit(
        conn, merchant_id, case_row, decision_row, refund, idempotency_key, now
    )
    set_case_status(conn, case_id, "refunded")

    return {
        "status": "refunded",
        "case_id": case_id,
        "refund_id": refund.refund_id,
        "amount_minor": int(refund.amount_minor),
        "currency": refund.currency,
        "rule_id": decision_row["rule_id"],
    }


# -- reads ------------------------------------------------------------------


def today_history(conn, merchant_id: str, now: datetime) -> History:
    day = iso(now)[:10]
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM audit "
        "WHERE merchant_id = ? AND substr(created_at, 1, 10) = ?",
        (merchant_id, day),
    ).fetchone()
    return History(refunds=(), today_total_minor=int(row["total"]))


def snapshot_from_order(order: Order) -> OrderSnapshot:
    if not order.captures:
        raise PolicyError("order %s has no capture" % (order.order_id,))
    capture = order.captures[0]
    return OrderSnapshot(
        order_id=order.order_id,
        capture_id=capture.capture_id,
        captured_amount_minor=capture.amount_minor,
        currency=capture.currency,
        created_at=order.created_at,
        refunded_amount_minor=capture.refunded_amount_minor,
    )


def list_cases(conn, merchant_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM cases WHERE merchant_id = ? ORDER BY created_at DESC",
        (merchant_id,),
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        item = row_to_dict(row)
        decision = conn.execute(
            "SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        audit = conn.execute(
            "SELECT * FROM audit WHERE case_id = ? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        item["decision"] = row_to_dict(decision)
        item["audit"] = row_to_dict(audit)
        out.append(item)
    return out


def case_detail(conn, merchant_id: str, case_id: str) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM cases WHERE id = ? AND merchant_id = ?",
        (case_id, merchant_id),
    ).fetchone()
    if row is None:
        raise PolicyError("case %s not found" % (case_id,))
    detail = row_to_dict(row)
    detail["decisions"] = [
        row_to_dict(item)
        for item in conn.execute(
            "SELECT * FROM decisions WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
    ]
    detail["audit_trail"] = [
        row_to_dict(item)
        for item in conn.execute(
            "SELECT * FROM audit WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
    ]
    detail["approvals"] = [
        row_to_dict(item)
        for item in conn.execute(
            "SELECT * FROM approvals WHERE case_id = ? ORDER BY id", (case_id,)
        ).fetchall()
    ]
    return detail


def list_approvals(conn, merchant_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM approvals WHERE merchant_id = ? ORDER BY created_at DESC",
        (merchant_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def totals(conn, merchant_id: str, now: datetime) -> Dict[str, Any]:
    day = iso(now)[:10]
    all_time = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS total, COUNT(*) AS count "
        "FROM audit WHERE merchant_id = ?",
        (merchant_id,),
    ).fetchone()
    today = conn.execute(
        "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM audit "
        "WHERE merchant_id = ? AND substr(created_at, 1, 10) = ?",
        (merchant_id, day),
    ).fetchone()
    pending = conn.execute(
        "SELECT COUNT(*) AS count FROM approvals "
        "WHERE merchant_id = ? AND status = 'pending'",
        (merchant_id,),
    ).fetchone()
    caps = get_caps(conn, merchant_id)
    return {
        "currency": caps.currency,
        "refunded_all_time_minor": int(all_time["total"]),
        "refund_count": int(all_time["count"]),
        "refunded_today_minor": int(today["total"]),
        "per_refund_max_minor": caps.per_refund_max_minor,
        "daily_total_max_minor": caps.daily_total_max_minor,
        "pending_approvals": int(pending["count"]),
    }
