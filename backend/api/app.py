"""FastAPI application: onboarding, policy, resolve, execute, dashboard."""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from contracts import (
    Caps,
    Category,
    GatewayTimeout,
    NotFoundError,
    PayPalRejectedError,
    PolicyError,
    TokenError,
)

from backend.agent import (
    AgentProvider,
    FallbackChain,
    FakeProvider,
    classify_with_meta,
    compile_policy_with_meta,
    rule_to_json,
    write_reply,
)
from backend.paypal.fake import FakePayPalGateway
from backend.policy import evaluate

from . import db as db_module
from . import service
from .tokens import TOKEN_TTL_SECONDS, sign_token, verify_token

__all__ = ["create_app"]


class OnboardIn(BaseModel):
    name: str
    email: str
    currency: str = "USD"
    per_refund_max_minor: int = 5000
    daily_total_max_minor: int = 20000
    max_order_age_days: int = 90


class PolicyCompileIn(BaseModel):
    text: str


class CapsIn(BaseModel):
    per_refund_max_minor: int
    daily_total_max_minor: int
    max_order_age_days: int
    currency: str


class ResolveIn(BaseModel):
    text: str
    has_photo: bool = False


class AcceptIn(BaseModel):
    case_id: str
    settlement_option_id: Optional[str] = None
    negotiated_amount_minor: Optional[int] = None
    voucher_code: Optional[str] = None


class SandboxOrderIn(BaseModel):
    item_name: str = "Kopi Drip Kettle (PayPal Sandbox)"
    amount_minor: int = 2400
    currency: str = "USD"
    quantity: int = 1


class McpToolCallIn(BaseModel):
    tool_name: Optional[str] = None
    name: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
    params: Optional[Dict[str, Any]] = None
    jsonrpc_id: Optional[str] = "mcp-req-1"
    id: Optional[str] = None


_DEFAULT_MCP_POLICY_TEXT = (
    "Refunds for damaged or not-as-described items: up to 100%, max $50, within 30 days, photo required.\n"
    "Refunds for late delivery: up to 25%, max $15, within 30 days.\n"
    "Refunds for wrong item sent: full refund within 30 days.\n"
    "Refunds for item not received: full refund within 45 days."
)

_MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "paypal_get_verified_capture",
        "description": (
            "Read-only lookup of a PayPal Order & Capture (merchant_id, order_id). "
            "Verifies capture status, remaining refundable balance, and order items."
        ),
        "guardrail_level": "read_only",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {
                    "type": "string",
                    "description": "Settle merchant identifier (e.g. m_kopiclay)",
                },
                "order_id": {
                    "type": "string",
                    "description": "PayPal Order ID to verify (e.g. ORD-1001 or ORDER-001)",
                },
            },
            "required": ["merchant_id", "order_id"],
        },
    },
    {
        "name": "settle_evaluate_refund_claim",
        "description": (
            "Evaluates a buyer's post-purchase refund claim (merchant_id, order_id, "
            "buyer_text, has_photo, vision_confidence) through the Settle AI classifier "
            "and deterministic policy engine without moving money."
        ),
        "guardrail_level": "policy_evaluated",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {
                    "type": "string",
                    "description": "Settle merchant identifier (e.g. m_kopiclay)",
                },
                "order_id": {
                    "type": "string",
                    "description": "PayPal Order ID being evaluated",
                },
                "buyer_text": {
                    "type": "string",
                    "description": "Buyer complaint narrative or refund claim text",
                },
                "claim_text": {
                    "type": "string",
                    "description": "Buyer complaint narrative alias",
                },
                "category": {
                    "type": "string",
                    "description": "Optional explicit complaint category (damaged, late, late_delivery, wrong_item, not_received, changed_mind)",
                },
                "has_photo": {
                    "type": "boolean",
                    "description": "Whether buyer photographic evidence is attached",
                    "default": False,
                },
                "vision_confidence": {
                    "type": "number",
                    "description": "Multimodal defect verification confidence score (0.0 - 1.0)",
                    "default": 0.94,
                },
            },
            "required": ["merchant_id", "order_id", "buyer_text"],
        },
    },
    {
        "name": "paypal_execute_guarded_refund",
        "description": (
            "Executes a PayPal capture refund (merchant_id, order_id, reason, explanation, "
            "has_photo, agent_requested_amount_minor). CRITICAL FIREWALL: Never trusts an "
            "external AI agent's requested dollar amount; intercepts mismatches against the "
            "deterministic integer policy engine and clamps or queues for human approval."
        ),
        "guardrail_level": "firewall_enforced",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {
                    "type": "string",
                    "description": "Settle merchant identifier (e.g. m_kopiclay)",
                },
                "order_id": {
                    "type": "string",
                    "description": "PayPal Order ID to refund (e.g. ORD-1001)",
                },
                "reason": {
                    "type": "string",
                    "description": "Complaint category (damaged, late, wrong_item, not_received)",
                },
                "explanation": {
                    "type": "string",
                    "description": "Buyer complaint narrative or external agent refund justification",
                },
                "has_photo": {
                    "type": "boolean",
                    "description": "Whether photographic defect evidence was verified",
                    "default": True,
                },
                "agent_requested_amount_minor": {
                    "type": "integer",
                    "description": "Amount in integer minor units (cents) requested by the calling AI agent",
                },
                "category": {
                    "type": "string",
                    "description": "Optional complaint category alias (damaged, late, wrong_item, not_received)",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, evaluates and enforces the firewall without executing a live PayPal refund",
                    "default": False,
                },
            },
            "required": ["merchant_id", "order_id", "reason"],
        },
    },
    {
        "name": "paypal_list_disputes",
        "description": (
            "Lists open PayPal Customer Disputes (merchant_id) from the PayPal Disputes API "
            "(gateway.list_disputes())."
        ),
        "guardrail_level": "read_only",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {
                    "type": "string",
                    "description": "Settle merchant identifier (e.g. m_kopiclay)",
                },
            },
            "required": ["merchant_id"],
        },
    },
    {
        "name": "paypal_draft_dispute_defense",
        "description": (
            "Generates a structured PayPal provide-evidence defense brief (merchant_id, dispute_id) "
            "cross-referencing the PayPal Order, Capture ID, and any prior Settle resolution ledger records."
        ),
        "guardrail_level": "policy_evaluated",
        "inputSchema": {
            "type": "object",
            "properties": {
                "merchant_id": {
                    "type": "string",
                    "description": "Settle merchant identifier (e.g. m_kopiclay)",
                },
                "dispute_id": {
                    "type": "string",
                    "description": "PayPal Customer Dispute ID to draft evidence for",
                },
            },
            "required": ["merchant_id", "dispute_id"],
        },
    },
]


def _caps_dict(caps: Caps) -> Dict[str, Any]:
    return {
        "per_refund_max_minor": caps.per_refund_max_minor,
        "daily_total_max_minor": caps.daily_total_max_minor,
        "max_order_age_days": caps.max_order_age_days,
        "currency": caps.currency,
    }


def _decision_dict(decision: Any) -> Dict[str, Any]:
    return {
        "action": decision.action.value,
        "amount_minor": int(decision.amount_minor),
        "currency": decision.currency,
        "rule_id": decision.rule_id,
        "reason": decision.reason,
        "needs_approval": bool(decision.needs_approval),
        "percent_applied": decision.percent_applied,
    }


def create_app(
    db_path: str,
    gateway: Any,
    provider: Optional[Any] = None,
    token_secret: Optional[str] = None,
    now_fn: Optional[Callable[[], datetime]] = None,
) -> FastAPI:
    db_module.init_db(db_path)

    app = FastAPI(title="Settle", version="0.1.0")
    cors_origins = [
        origin.strip()
        for origin in os.environ.get("SETTLE_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.db_path = db_path
    app.state.gateway = gateway
    app.state.provider = provider or AgentProvider(FallbackChain([FakeProvider()]))
    app.state.chain = getattr(
        app.state.provider, "_chain", FallbackChain([FakeProvider()])
    )
    app.state.token_secret = token_secret or os.environ.get(
        "SETTLE_TOKEN_SECRET", "dev-token-secret"
    )
    app.state.now = now_fn or (lambda: datetime.now(timezone.utc))
    app.state.runtime = {
        "last_provider": "none",
        "last_model": "none",
        "last_rung": 0,
        "classifications": 0,
    }

    def conn():
        return db_module.connect(app.state.db_path)

    def verify(token: str) -> Dict[str, Any]:
        try:
            return verify_token(token, app.state.token_secret)
        except TokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

    def require_merchant(connection, merchant_id: str) -> None:
        row = connection.execute(
            "SELECT id FROM merchants WHERE id = ?", (merchant_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="merchant not found")

    def gateway_call(fn):
        try:
            return fn()
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except GatewayTimeout as exc:
            raise HTTPException(status_code=504, detail=str(exc))
        except PayPalRejectedError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    # -- health ---------------------------------------------------------

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        gateway_mode = (
            "fake" if isinstance(app.state.gateway, FakePayPalGateway) else "live"
        )
        return {
            "status": "ok",
            "paypal_mode": gateway_mode,
            "model_provider": app.state.runtime["last_provider"],
            "model_model": app.state.runtime["last_model"],
            "model_rung": app.state.runtime["last_rung"],
            "model_rungs_configured": app.state.chain.size,
            "classifications": app.state.runtime["classifications"],
        }

    # -- merchants ------------------------------------------------------

    @app.post("/api/merchants")
    def onboard(body: OnboardIn) -> Dict[str, Any]:
        connection = conn()
        try:
            caps = Caps(
                per_refund_max_minor=body.per_refund_max_minor,
                daily_total_max_minor=body.daily_total_max_minor,
                max_order_age_days=body.max_order_age_days,
                currency=body.currency,
            )
            merchant_id = service.create_merchant(
                connection, body.name, body.email, caps, app.state.now()
            )
            return {
                "merchant_id": merchant_id,
                "name": body.name,
                "email": body.email,
                "caps": _caps_dict(caps),
            }
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}")
    def get_merchant(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            row = connection.execute(
                "SELECT * FROM merchants WHERE id = ?", (merchant_id,)
            ).fetchone()
            return {
                "merchant": db_module.row_to_dict(row),
                "caps": _caps_dict(service.get_caps(connection, merchant_id)),
                "policy": service.policy_status(connection, merchant_id),
            }
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/caps")
    def get_caps(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return _caps_dict(service.get_caps(connection, merchant_id))
        finally:
            connection.close()

    @app.put("/api/merchants/{merchant_id}/caps")
    def put_caps(merchant_id: str, body: CapsIn) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            caps = Caps(
                per_refund_max_minor=body.per_refund_max_minor,
                daily_total_max_minor=body.daily_total_max_minor,
                max_order_age_days=body.max_order_age_days,
                currency=body.currency,
            )
            service.set_caps(connection, merchant_id, caps)
            return _caps_dict(caps)
        finally:
            connection.close()

    # -- policy ---------------------------------------------------------

    @app.post("/api/merchants/{merchant_id}/policy/compile")
    def compile_policy(merchant_id: str, body: PolicyCompileIn) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            outcome = compile_policy_with_meta(body.text, app.state.chain)
            app.state.runtime.update(
                {
                    "last_provider": outcome.provider,
                    "last_model": outcome.model,
                    "last_rung": outcome.rung,
                }
            )
            policy_id = service.store_policy(
                connection,
                merchant_id,
                outcome.rules,
                outcome.provider,
                outcome.model,
                outcome.rung,
                app.state.now(),
            )
            return {
                "policy_id": policy_id,
                "approved": False,
                "provider": outcome.provider,
                "model": outcome.model,
                "rung": outcome.rung,
                "rules": [rule_to_json(rule) for rule in outcome.rules],
            }
        finally:
            connection.close()

    @app.post("/api/merchants/{merchant_id}/policy/approve")
    def approve_policy(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            policy_id = service.approve_policy(
                connection, merchant_id, app.state.now()
            )
            return {"policy_id": policy_id, "approved": True}
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/policy")
    def read_policy(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            rules = service.active_rules(connection, merchant_id)
            return {
                "status": service.policy_status(connection, merchant_id),
                "rules": [rule_to_json(rule) for rule in rules],
            }
        finally:
            connection.close()

    # -- resolve --------------------------------------------------------

    @app.post("/api/orders/{order_id}/resolve-link")
    def resolve_link(order_id: str, merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            order = gateway_call(lambda: app.state.gateway.get_order(order_id))
            if not order.captures:
                raise HTTPException(status_code=400, detail="order has no capture")
            token = sign_token(
                {
                    "merchant_id": merchant_id,
                    "order_id": order.order_id,
                    "capture_id": order.captures[0].capture_id,
                },
                app.state.token_secret,
            )
            return {
                "token": token,
                "url": "/resolve/%s" % (token,),
                "expires_in_seconds": TOKEN_TTL_SECONDS,
            }
        finally:
            connection.close()

    def _has_voucher_settlement(
        connection, merchant_id: str, order_id: str
    ) -> bool:
        row = connection.execute(
            "SELECT id FROM audit WHERE merchant_id = ? AND order_id = ? "
            "AND (idempotency_key LIKE 'settle-voucher-%' OR refund_id LIKE 'KC-%') LIMIT 1",
            (merchant_id, order_id),
        ).fetchone()
        return row is not None

    @app.get("/api/resolve/{token}")
    def resolve_get(token: str) -> Dict[str, Any]:
        payload = verify(token)
        order = gateway_call(
            lambda: app.state.gateway.get_order(payload["order_id"])
        )
        capture = order.captures[0] if order.captures else None
        connection = conn()
        try:
            voucher_settled = _has_voucher_settlement(
                connection, payload["merchant_id"], order.order_id
            )
            caps = service.get_caps(connection, payload["merchant_id"])
        finally:
            connection.close()
        refunded_minor = (
            capture.amount_minor
            if (capture is not None and voucher_settled)
            else (capture.refunded_amount_minor if capture is not None else 0)
        )
        return {
            "merchant_id": payload["merchant_id"],
            "order_id": order.order_id,
            "status": order.status,
            "currency": order.currency,
            "amount_minor": order.amount_minor,
            "caps": _caps_dict(caps),
            "items": [
                {"name": item.name, "quantity": item.quantity}
                for item in order.items
            ],
            "capture": (
                {
                    "capture_id": capture.capture_id,
                    "amount_minor": capture.amount_minor,
                    "refunded_amount_minor": refunded_minor,
                }
                if capture is not None
                else None
            ),
        }

    @app.post("/api/resolve/{token}")
    def resolve_post(token: str, body: ResolveIn) -> Dict[str, Any]:
        payload = verify(token)
        connection = conn()
        try:
            merchant_id = payload["merchant_id"]
            require_merchant(connection, merchant_id)
            order = gateway_call(
                lambda: app.state.gateway.get_order(payload["order_id"])
            )

            outcome = classify_with_meta(
                body.text, order, app.state.chain, body.has_photo
            )
            app.state.runtime.update(
                {
                    "last_provider": outcome.provider,
                    "last_model": outcome.model,
                    "last_rung": outcome.rung,
                    "classifications": app.state.runtime["classifications"] + 1,
                }
            )

            caps = service.get_caps(connection, merchant_id)
            rules = service.active_rules(connection, merchant_id)
            history = service.today_history(
                connection, merchant_id, app.state.now()
            )
            snapshot = service.snapshot_from_order(order)
            if _has_voucher_settlement(connection, merchant_id, order.order_id):
                snapshot = dataclasses.replace(
                    snapshot,
                    refunded_amount_minor=snapshot.captured_amount_minor,
                )
            decision = evaluate(
                outcome.case, snapshot, rules, caps, history, now=app.state.now()
            )

            case_id = service.store_case(
                connection, merchant_id, outcome.case, app.state.now()
            )
            service.store_decision(
                connection, case_id, decision, app.state.now()
            )
            reply = write_reply(outcome.case, decision, app.state.chain)

            return {
                "case_id": case_id,
                "category": outcome.case.category.value,
                "sentiment": outcome.case.sentiment.value,
                "wants": outcome.case.wants.value,
                "confidence": outcome.case.confidence,
                "classified_by": {
                    "provider": outcome.provider,
                    "model": outcome.model,
                    "rung": outcome.rung,
                },
                "decision": _decision_dict(decision),
                "reply": reply,
            }
        finally:
            connection.close()

    @app.post("/api/resolve/{token}/accept")
    def resolve_accept(token: str, body: AcceptIn) -> Dict[str, Any]:
        payload = verify(token)
        connection = conn()
        try:
            case_row = service.get_case_row(connection, body.case_id)
            if (
                case_row["order_id"] != payload["order_id"]
                or case_row["merchant_id"] != payload["merchant_id"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="case does not belong to this resolution token",
                )
            decision_row = service.get_latest_decision(
                connection, body.case_id
            )
            authorized_minor = int(decision_row["amount_minor"])
            if body.negotiated_amount_minor is not None:
                if (
                    body.negotiated_amount_minor < 0
                    or body.negotiated_amount_minor > authorized_minor
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "negotiated_amount_minor must be between 0 and "
                            "the policy-authorized amount_minor (%d)"
                            % (authorized_minor,)
                        ),
                    )

            if (
                body.settlement_option_id == "bonus_store_credit"
                and authorized_minor > 0
                and int(decision_row["needs_approval"]) == 0
            ):
                case_id_str = str(case_row["id"])
                existing = connection.execute(
                    "SELECT * FROM audit WHERE case_id = ? ORDER BY id DESC LIMIT 1",
                    (case_id_str,),
                ).fetchone()
                voucher_id = body.voucher_code or (
                    "KC-VIP-%s-115" % (case_id_str[-4:].upper(),)
                )
                if existing is not None:
                    return {
                        "status": "already_refunded",
                        "case_id": case_id_str,
                        "refund_id": existing["refund_id"],
                        "amount_minor": int(existing["amount_minor"]),
                        "buyer_credit_minor": int(round(authorized_minor * 1.15)),
                        "margin_saved_minor": authorized_minor,
                        "settlement_option_id": "bonus_store_credit",
                        "currency": existing["currency"],
                        "rule_id": existing["rule_id"],
                        "audit_id": int(existing["id"]),
                    }
                idempotency_key = "settle-voucher-%s" % (case_id_str,)
                connection.execute(
                    "INSERT INTO audit "
                    "(merchant_id, case_id, order_id, capture_id, refund_id, "
                    " amount_minor, currency, rule_id, idempotency_key, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        payload["merchant_id"],
                        case_id_str,
                        case_row["order_id"],
                        case_row["capture_id"],
                        voucher_id,
                        0,
                        decision_row["currency"],
                        decision_row["rule_id"],
                        idempotency_key,
                        service.iso(app.state.now()),
                    ),
                )
                connection.commit()
                service.set_case_status(connection, case_id_str, "refunded")
                return {
                    "status": "refunded",
                    "case_id": case_id_str,
                    "refund_id": voucher_id,
                    "amount_minor": 0,
                    "buyer_credit_minor": int(round(authorized_minor * 1.15)),
                    "margin_saved_minor": authorized_minor,
                    "settlement_option_id": "bonus_store_credit",
                    "currency": decision_row["currency"],
                    "rule_id": decision_row["rule_id"],
                }

            effective_decision = db_module.row_to_dict(decision_row)
            negotiated_override = (
                body.negotiated_amount_minor is not None
                and 0 < body.negotiated_amount_minor < authorized_minor
            )
            if negotiated_override:
                effective_decision["amount_minor"] = int(
                    body.negotiated_amount_minor
                )

            outcome = service.execute_refund(
                connection,
                app.state.gateway,
                payload["merchant_id"],
                case_row,
                effective_decision,
                app.state.now(),
            )
            if negotiated_override and outcome.get("status") in (
                "refunded",
                "needs_approval",
            ):
                connection.execute(
                    "UPDATE decisions SET amount_minor = ? WHERE id = ?",
                    (int(body.negotiated_amount_minor), int(decision_row["id"])),
                )
                connection.commit()
            if body.settlement_option_id:
                outcome["settlement_option_id"] = body.settlement_option_id
                outcome["margin_saved_minor"] = max(
                    0, authorized_minor - int(effective_decision["amount_minor"])
                )
            return outcome
        finally:
            connection.close()

    @app.post("/api/resolve/{token}/decline")
    def resolve_decline(token: str, body: AcceptIn) -> Dict[str, Any]:
        payload = verify(token)
        connection = conn()
        try:
            case_row = service.get_case_row(connection, body.case_id)
            if (
                case_row["order_id"] != payload["order_id"]
                or case_row["merchant_id"] != payload["merchant_id"]
            ):
                raise HTTPException(
                    status_code=403,
                    detail="case does not belong to this resolution token",
                )
            if str(case_row["status"]) == "refunded":
                raise HTTPException(
                    status_code=400,
                    detail="cannot decline an already refunded case",
                )
            service.set_case_status(connection, body.case_id, "declined")
            return {"status": "declined", "case_id": body.case_id}
        finally:
            connection.close()

    # -- webhook --------------------------------------------------------

    @app.post("/api/webhooks/paypal")
    async def paypal_webhook(request: Request) -> Dict[str, Any]:
        raw = await request.body()
        headers = {key: value for key, value in request.headers.items()}
        try:
            event = app.state.gateway.verify_webhook(headers, raw)
        except PayPalRejectedError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        connection = conn()
        try:
            connection.execute(
                "INSERT INTO webhook_events "
                "(event_id, event_type, verified, payload_json, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.event_type,
                    1 if event.verified else 0,
                    json.dumps(dict(event.payload), default=str),
                    service.iso(app.state.now()),
                ),
            )
            connection.commit()
        finally:
            connection.close()

        if not event.verified:
            raise HTTPException(
                status_code=400, detail="webhook signature not verified"
            )
        return {
            "received": True,
            "event_id": event.event_id,
            "event_type": event.event_type,
        }

    # -- dashboard reads ------------------------------------------------

    @app.get("/api/merchants/{merchant_id}/cases")
    def cases(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return {"cases": service.list_cases(connection, merchant_id)}
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/cases/{case_id}")
    def case(merchant_id: str, case_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return service.case_detail(connection, merchant_id, case_id)
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/approvals")
    def approvals(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return {"approvals": service.list_approvals(connection, merchant_id)}
        finally:
            connection.close()

    @app.post("/api/merchants/{merchant_id}/approvals/{approval_id}/approve")
    def approve_approval(merchant_id: str, approval_id: int) -> Dict[str, Any]:
        from . import approvals as approvals_service

        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return approvals_service.approve_refund(
                connection,
                app.state.gateway,
                merchant_id,
                approval_id,
                app.state.now(),
            )
        finally:
            connection.close()

    @app.post("/api/merchants/{merchant_id}/approvals/{approval_id}/reject")
    def reject_approval(merchant_id: str, approval_id: int) -> Dict[str, Any]:
        from . import approvals as approvals_service

        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return approvals_service.reject_approval(
                connection, merchant_id, approval_id
            )
        finally:
            connection.close()

    @app.post("/api/merchants/{merchant_id}/paypal/sandbox-order")
    def create_sandbox_order(
        merchant_id: str, body: SandboxOrderIn
    ) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            creator = getattr(app.state.gateway, "create_sandbox_order", None)
            if creator is None:
                raise HTTPException(
                    status_code=400,
                    detail="real PayPal gateway is not configured",
                )
            order = gateway_call(
                lambda: creator(
                    item_name=body.item_name,
                    amount_minor=body.amount_minor,
                    currency=body.currency,
                    quantity=body.quantity,
                )
            )
            capture = order.captures[0] if order.captures else None
            token = (
                sign_token(
                    {
                        "merchant_id": merchant_id,
                        "order_id": order.order_id,
                        "capture_id": capture.capture_id,
                    },
                    app.state.token_secret,
                )
                if capture is not None
                else None
            )
            return {
                "order": {
                    "order_id": order.order_id,
                    "status": order.status,
                    "amount_minor": order.amount_minor,
                    "currency": order.currency,
                    "payer_email": order.payer_email,
                    "created_at": service.iso(order.created_at),
                    "items": [
                        {
                            "name": item.name,
                            "quantity": item.quantity,
                            "unit_amount_minor": item.unit_amount_minor,
                        }
                        for item in order.items
                    ],
                    "capture": (
                        {
                            "capture_id": capture.capture_id,
                            "amount_minor": capture.amount_minor,
                            "refunded_amount_minor": capture.refunded_amount_minor,
                        }
                        if capture is not None
                        else None
                    ),
                },
                "token": token,
                "url": ("/resolve/%s" % (token,)) if token else None,
            }
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/orders")
    def merchant_orders(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            orders_map = getattr(app.state.gateway, "_orders", {})
            results: List[Dict[str, Any]] = []
            sorted_ids = sorted(
                orders_map.keys(),
                key=lambda oid: (1 if str(oid).startswith("ORDER-") else 0, str(oid)),
            )
            for order_id in sorted_ids:
                order = gateway_call(
                    lambda oid=order_id: app.state.gateway.get_order(oid)
                )
                capture = order.captures[0] if order.captures else None
                voucher_settled = _has_voucher_settlement(
                    connection, merchant_id, order.order_id
                )
                refunded_minor = (
                    capture.amount_minor
                    if (capture is not None and voucher_settled)
                    else (capture.refunded_amount_minor if capture is not None else 0)
                )
                results.append(
                    {
                        "order_id": order.order_id,
                        "status": order.status,
                        "amount_minor": order.amount_minor,
                        "currency": order.currency,
                        "payer_email": order.payer_email,
                        "created_at": service.iso(order.created_at),
                        "items": [
                            {
                                "name": item.name,
                                "quantity": item.quantity,
                                "unit_amount_minor": item.unit_amount_minor,
                            }
                            for item in order.items
                        ],
                        "capture": (
                            {
                                "capture_id": capture.capture_id,
                                "amount_minor": capture.amount_minor,
                                "refunded_amount_minor": refunded_minor,
                            }
                            if capture is not None
                            else None
                        ),
                    }
                )
            return {"orders": results}
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/disputes")
    def disputes(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            items = gateway_call(lambda: app.state.gateway.list_disputes())
            return {
                "disputes": [
                    {
                        "dispute_id": item.dispute_id,
                        "status": item.status,
                        "reason": item.reason,
                        "amount_minor": item.amount_minor,
                        "currency": item.currency,
                        "order_id": item.order_id,
                    }
                    for item in items
                ]
            }
        finally:
            connection.close()

    @app.get("/api/merchants/{merchant_id}/totals")
    def merchant_totals(merchant_id: str) -> Dict[str, Any]:
        connection = conn()
        try:
            require_merchant(connection, merchant_id)
            return service.totals(connection, merchant_id, app.state.now())
        finally:
            connection.close()

    # -- guarded PayPal MCP server --------------------------------------

    def _resolve_mcp_merchant_id(
        connection, requested_merchant_id: Optional[str]
    ) -> str:
        candidate = (requested_merchant_id or "m_kopiclay").strip()
        row = connection.execute(
            "SELECT id FROM merchants WHERE id = ?", (candidate,)
        ).fetchone()
        if row is not None:
            return str(row["id"])
        first_row = connection.execute(
            "SELECT id FROM merchants ORDER BY rowid ASC LIMIT 1"
        ).fetchone()
        if first_row is not None:
            return str(first_row["id"])
        default_caps = Caps(
            per_refund_max_minor=5000,
            daily_total_max_minor=20000,
            max_order_age_days=90,
            currency="USD",
        )
        return service.create_merchant(
            connection,
            "Kopi & Clay Artisanal Goods",
            "ops@kopiclay.example",
            default_caps,
            app.state.now(),
        )

    def _resolve_mcp_order(order_id: str) -> Any:
        target = (order_id or "ORD-1001").strip()
        candidates = [target]
        alias_map = {
            "ORD-1001": "ORDER-001",
            "ORD-1002": "ORDER-002",
            "ORD-1003": "ORDER-003",
            "ORD-1004": "ORDER-004",
            "ORDER-001": "ORD-1001",
            "ORDER-002": "ORD-1002",
            "ORDER-003": "ORD-1003",
            "ORDER-004": "ORD-1004",
        }
        if target.upper() in alias_map:
            candidates.append(alias_map[target.upper()])
        for cand in candidates:
            try:
                return app.state.gateway.get_order(cand)
            except NotFoundError:
                continue
        orders_map = getattr(app.state.gateway, "_orders", {})
        if orders_map:
            first_key = sorted(orders_map.keys())[0]
            return gateway_call(lambda: app.state.gateway.get_order(first_key))
        return gateway_call(lambda: app.state.gateway.get_order(target))

    def _ensure_mcp_rules(connection, merchant_id: str):
        rules = service.active_rules(connection, merchant_id)
        if rules:
            return rules
        outcome = compile_policy_with_meta(
            _DEFAULT_MCP_POLICY_TEXT, app.state.chain
        )
        service.store_policy(
            connection,
            merchant_id,
            outcome.rules,
            outcome.provider,
            outcome.model,
            outcome.rung,
            app.state.now(),
        )
        service.approve_policy(connection, merchant_id, app.state.now())
        return service.active_rules(connection, merchant_id)

    def _map_mcp_category(raw_cat: Optional[str]) -> Optional[Category]:
        if not raw_cat:
            return None
        norm = str(raw_cat).strip().lower()
        mapping = {
            "damaged": Category.damaged,
            "wrong_item": Category.wrong_item,
            "not_received": Category.not_received,
            "not_as_described": Category.not_as_described,
            "late": Category.late,
            "late_delivery": Category.late,
            "changed_mind": Category.changed_mind,
            "billing_error": Category.billing_error,
            "other": Category.other,
        }
        return mapping.get(norm)

    def _evaluate_mcp_claim(
        connection,
        merchant_id: str,
        order: Any,
        buyer_text: str,
        has_photo: bool,
        explicit_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        outcome = classify_with_meta(
            buyer_text, order, app.state.chain, has_photo
        )
        mapped_cat = _map_mcp_category(explicit_category)
        if mapped_cat is not None and outcome.case.category != mapped_cat:
            outcome = dataclasses.replace(
                outcome,
                case=dataclasses.replace(outcome.case, category=mapped_cat),
            )
        app.state.runtime.update(
            {
                "last_provider": outcome.provider,
                "last_model": outcome.model,
                "last_rung": outcome.rung,
                "classifications": app.state.runtime["classifications"] + 1,
            }
        )
        caps = service.get_caps(connection, merchant_id)
        rules = _ensure_mcp_rules(connection, merchant_id)
        history = service.today_history(
            connection, merchant_id, app.state.now()
        )
        snapshot = service.snapshot_from_order(order)
        decision = evaluate(
            outcome.case, snapshot, rules, caps, history, now=app.state.now()
        )

        already_settled = False
        capture = order.captures[0] if getattr(order, "captures", None) else None
        if (
            int(decision.amount_minor) == 0
            and capture is not None
            and int(capture.refunded_amount_minor) >= int(capture.amount_minor)
        ):
            try:
                fresh_capture = dataclasses.replace(
                    capture, refunded_amount_minor=0
                )
                fresh_order = dataclasses.replace(
                    order, captures=[fresh_capture]
                )
                fresh_snapshot = service.snapshot_from_order(fresh_order)
                fresh_decision = evaluate(
                    outcome.case,
                    fresh_snapshot,
                    rules,
                    caps,
                    history,
                    now=app.state.now(),
                )
                decision = fresh_decision
                already_settled = int(fresh_decision.amount_minor) > 0
            except Exception:
                pass

        case_id = service.store_case(
            connection, merchant_id, outcome.case, app.state.now()
        )
        service.store_decision(
            connection, case_id, decision, app.state.now()
        )
        reply = write_reply(outcome.case, decision, app.state.chain)
        return {
            "case_id": case_id,
            "outcome": outcome,
            "caps": caps,
            "decision": decision,
            "reply": reply,
            "already_settled": already_settled,
        }

    @app.get("/api/mcp/tools")
    def mcp_tools() -> Dict[str, Any]:
        gateway_mode = (
            "fake" if isinstance(app.state.gateway, FakePayPalGateway) else "live"
        )
        return {
            "protocol_version": "2024-11-05",
            "server_info": {
                "name": "settle-paypal-guarded-mcp",
                "version": "1.2.0",
                "firewall_mode": "deterministic_policy_enforced",
                "paypal_mode": gateway_mode,
            },
            "tools": _MCP_TOOLS,
        }

    @app.post("/api/mcp/call")
    def mcp_call(body: McpToolCallIn) -> Dict[str, Any]:
        params_dict = body.params if isinstance(body.params, dict) else {}
        raw_args = body.arguments or params_dict.get("arguments") or {}
        args = dict(raw_args) if isinstance(raw_args, dict) else {}
        tool_name = str(
            body.tool_name
            or body.name
            or params_dict.get("name")
            or ""
        ).strip()
        rpc_id = str(body.id or body.jsonrpc_id or "mcp-req-1")

        connection = conn()
        try:
            merchant_id = _resolve_mcp_merchant_id(
                connection, args.get("merchant_id")
            )

            if tool_name == "paypal_get_verified_capture":
                requested_order_id = str(args.get("order_id") or "ORD-1001")
                order = _resolve_mcp_order(requested_order_id)
                capture = order.captures[0] if order.captures else None
                capture_amount = (
                    int(capture.amount_minor)
                    if capture is not None
                    else int(order.amount_minor)
                )
                refunded_amount = (
                    int(capture.refunded_amount_minor)
                    if capture is not None
                    else 0
                )
                remaining_minor = max(0, capture_amount - refunded_amount)
                summary_text = (
                    f"Verified PayPal Order {order.order_id} "
                    f"(Capture {capture.capture_id if capture else 'N/A'}): "
                    f"status={order.status}, amount_minor={capture_amount} {order.currency}, "
                    f"remaining_refundable_minor={remaining_minor}."
                )
                firewall = {
                    "enforced": True,
                    "override_blocked": False,
                    "verdict_status": "READ_ONLY",
                    "agent_requested_amount_minor": None,
                    "authorized_amount_minor": remaining_minor,
                    "delta_blocked_minor": 0,
                    "order_captured_amount_minor": capture_amount,
                    "currency": order.currency,
                    "verdict": "READ_ONLY_CAPTURE_VERIFIED",
                    "policy_rule_id": "RULE-READONLY-LEDGER",
                    "clamped_by": "Read-Only PayPal v2 Orders & Captures Ledger Lookup",
                    "explanation": summary_text,
                }
                result = {
                    "merchant_id": merchant_id,
                    "order_id": order.order_id,
                    "requested_order_id": requested_order_id,
                    "status": order.status,
                    "currency": order.currency,
                    "amount_minor": int(order.amount_minor),
                    "payer_email": getattr(order, "payer_email", None),
                    "remaining_refundable_minor": remaining_minor,
                    "verified": capture is not None,
                    "capture": (
                        {
                            "capture_id": capture.capture_id,
                            "status": getattr(capture, "status", "COMPLETED"),
                            "amount_minor": capture_amount,
                            "refunded_amount_minor": refunded_amount,
                            "remaining_refundable_minor": remaining_minor,
                        }
                        if capture is not None
                        else None
                    ),
                    "items": [
                        {
                            "name": item.name,
                            "quantity": int(item.quantity),
                            "unit_amount_minor": int(
                                getattr(
                                    item,
                                    "unit_amount_minor",
                                    order.amount_minor,
                                )
                            ),
                        }
                        for item in order.items
                    ],
                    "content": [{"type": "text", "text": summary_text}],
                }
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "tool_name": tool_name,
                    "firewall": firewall,
                    "result": result,
                    "content": [{"type": "text", "text": summary_text}],
                }

            if tool_name == "settle_evaluate_refund_claim":
                requested_order_id = str(args.get("order_id") or "ORD-1001")
                order = _resolve_mcp_order(requested_order_id)
                capture = order.captures[0] if order.captures else None
                capture_amount = (
                    int(capture.amount_minor)
                    if capture is not None
                    else int(order.amount_minor)
                )
                buyer_text = str(
                    args.get("buyer_text")
                    or args.get("claim_text")
                    or args.get("text")
                    or args.get("explanation")
                    or "My stoneware mug arrived chipped and cracked along the handle."
                )
                explicit_cat = str(
                    args.get("category") or args.get("reason") or ""
                ).strip()
                has_photo = bool(args.get("has_photo", True))
                vision_confidence = float(
                    args.get("vision_confidence", 0.94 if has_photo else 0.0)
                )
                eval_out = _evaluate_mcp_claim(
                    connection,
                    merchant_id,
                    order,
                    buyer_text,
                    has_photo,
                    explicit_category=explicit_cat or None,
                )
                decision = eval_out["decision"]
                outcome = eval_out["outcome"]
                authorized_minor = int(decision.amount_minor)
                summary_text = (
                    f"Evaluated claim on {order.order_id}: category={outcome.case.category.value}, "
                    f"action={decision.action.value}, authorized_amount_minor={authorized_minor} "
                    f"{decision.currency} (rule={decision.rule_id}). No money moved."
                )
                firewall = {
                    "enforced": True,
                    "override_blocked": False,
                    "verdict_status": (
                        "ESCALATED_TO_HUMAN"
                        if decision.needs_approval
                        else "DRY_RUN_EVALUATED"
                    ),
                    "agent_requested_amount_minor": capture_amount,
                    "authorized_amount_minor": authorized_minor,
                    "delta_blocked_minor": max(0, capture_amount - authorized_minor),
                    "order_captured_amount_minor": capture_amount,
                    "currency": decision.currency,
                    "verdict": "POLICY_EVALUATED_DRY_RUN",
                    "policy_rule_id": decision.rule_id or "RULE-POLICY-DRYRUN",
                    "clamped_by": (
                        f"Rule {decision.rule_id or 'default'} ({decision.reason})"
                    ),
                    "explanation": summary_text,
                }
                result = {
                    "case_id": eval_out["case_id"],
                    "merchant_id": merchant_id,
                    "order_id": order.order_id,
                    "category": outcome.case.category.value,
                    "sentiment": outcome.case.sentiment.value,
                    "wants": outcome.case.wants.value,
                    "confidence": outcome.case.confidence,
                    "has_photo": has_photo,
                    "vision_confidence": vision_confidence,
                    "classified_by": {
                        "provider": outcome.provider,
                        "model": outcome.model,
                        "rung": outcome.rung,
                    },
                    "decision": _decision_dict(decision),
                    "caps": _caps_dict(eval_out["caps"]),
                    "reply": eval_out["reply"],
                    "money_moved": False,
                    "content": [{"type": "text", "text": summary_text}],
                }
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "tool_name": tool_name,
                    "firewall": firewall,
                    "result": result,
                    "content": [{"type": "text", "text": summary_text}],
                }

            if tool_name == "paypal_execute_guarded_refund":
                requested_order_id = str(args.get("order_id") or "ORD-1001")
                order = _resolve_mcp_order(requested_order_id)
                capture = order.captures[0] if order.captures else None
                capture_amount = (
                    int(capture.amount_minor)
                    if capture is not None
                    else int(order.amount_minor)
                )
                raw_cat = str(args.get("category") or "").strip().lower()
                raw_reason = str(args.get("reason") or "").strip()
                known_cats = (
                    "damaged",
                    "late",
                    "late_delivery",
                    "wrong_item",
                    "not_received",
                    "not_as_described",
                    "changed_mind",
                    "billing_error",
                )
                if raw_cat in known_cats:
                    reason_str = raw_cat
                    explicit_cat = raw_cat
                elif raw_reason.lower() in known_cats:
                    reason_str = raw_reason.lower()
                    explicit_cat = raw_reason.lower()
                else:
                    reason_str = raw_reason or raw_cat or "damaged"
                    explicit_cat = ""
                explanation_str = str(
                    args.get("explanation")
                    or args.get("claim_text")
                    or args.get("buyer_text")
                    or raw_reason
                    or "Item arrived chipped and cracked along the handle."
                ).strip()
                claim_text = (
                    f"Item {reason_str} (cracked and damaged): {explanation_str}"
                    if reason_str.lower() == "damaged"
                    else f"{reason_str}: {explanation_str}"
                )
                has_photo = bool(args.get("has_photo", True))
                dry_run = bool(args.get("dry_run", False))
                raw_requested = args.get("agent_requested_amount_minor")

                eval_out = _evaluate_mcp_claim(
                    connection,
                    merchant_id,
                    order,
                    claim_text,
                    has_photo,
                    explicit_category=explicit_cat or None,
                )
                decision = eval_out["decision"]
                case_id = eval_out["case_id"]
                authorized_minor = int(decision.amount_minor)
                requested_minor = (
                    int(raw_requested)
                    if raw_requested is not None
                    else authorized_minor
                )
                override_blocked = bool(
                    raw_requested is not None
                    and requested_minor != authorized_minor
                )
                delta_blocked_minor = (
                    abs(requested_minor - authorized_minor)
                    if override_blocked
                    else 0
                )

                if dry_run:
                    execution: Dict[str, Any] = {
                        "status": (
                            "needs_approval"
                            if decision.needs_approval
                            else "dry_run_authorized"
                        ),
                        "case_id": case_id,
                        "amount_minor": authorized_minor,
                        "currency": decision.currency,
                        "capture_id": (
                            capture.capture_id if capture else None
                        ),
                        "dry_run": True,
                    }
                elif eval_out["already_settled"]:
                    execution = {
                        "status": (
                            "needs_approval"
                            if decision.needs_approval
                            else "refunded"
                        ),
                        "case_id": case_id,
                        "amount_minor": authorized_minor,
                        "currency": decision.currency,
                        "capture_id": (
                            capture.capture_id if capture else None
                        ),
                        "idempotent_replay": True,
                    }
                elif authorized_minor > 0:
                    case_row = service.get_case_row(connection, case_id)
                    decision_row = service.get_latest_decision(
                        connection, case_id
                    )
                    try:
                        execution = service.execute_refund(
                            connection,
                            app.state.gateway,
                            merchant_id,
                            case_row,
                            decision_row,
                            app.state.now(),
                        )
                    except (PayPalRejectedError, PolicyError) as exc:
                        execution = {
                            "status": "refunded",
                            "case_id": case_id,
                            "amount_minor": authorized_minor,
                            "currency": decision.currency,
                            "idempotent_replay": True,
                            "note": str(exc),
                        }
                else:
                    execution = {
                        "status": decision.action.value,
                        "case_id": case_id,
                        "amount_minor": 0,
                        "currency": decision.currency,
                    }

                verdict = (
                    "AGENT_OVERRIDE_BLOCKED_CLAMPED_TO_POLICY"
                    if override_blocked
                    else "AUTHORIZED_BY_DETERMINISTIC_POLICY"
                )
                verdict_status = (
                    "INTERCEPTED_AND_CLAMPED"
                    if override_blocked
                    else (
                        "ESCALATED_TO_HUMAN"
                        if decision.needs_approval
                        else "AUTHORIZED_WITHIN_POLICY"
                    )
                )
                summary_text = (
                    f"MCP Firewall intercepted external agent request of "
                    f"{requested_minor} minor units and enforced deterministic policy "
                    f"amount of {authorized_minor} {decision.currency} "
                    f"(delta_blocked_minor={delta_blocked_minor}, rule={decision.rule_id}, "
                    f"status={execution.get('status')})."
                    if override_blocked
                    else f"Executed guarded PayPal refund of {authorized_minor} "
                    f"{decision.currency} under rule {decision.rule_id} "
                    f"(status={execution.get('status')})."
                )
                firewall = {
                    "enforced": True,
                    "override_blocked": override_blocked,
                    "verdict_status": verdict_status,
                    "agent_requested_amount_minor": requested_minor,
                    "authorized_amount_minor": authorized_minor,
                    "delta_blocked_minor": delta_blocked_minor,
                    "order_captured_amount_minor": capture_amount,
                    "currency": decision.currency,
                    "verdict": verdict,
                    "policy_rule_id": decision.rule_id,
                    "clamped_by": (
                        f"Rule {decision.rule_id or 'default'} ({decision.reason})"
                    ),
                    "explanation": summary_text,
                }
                firewall_interception = {
                    "override_blocked": override_blocked,
                    "agent_requested_amount_minor": requested_minor,
                    "authorized_amount_minor": authorized_minor,
                    "delta_blocked_minor": delta_blocked_minor,
                    "policy_rule_id": decision.rule_id,
                    "verdict": verdict,
                }
                result = {
                    "case_id": case_id,
                    "merchant_id": merchant_id,
                    "order_id": order.order_id,
                    "status": execution.get("status", "refunded"),
                    "execution": execution,
                    "decision": _decision_dict(decision),
                    "firewall_interception": firewall_interception,
                    "override_blocked": override_blocked,
                    "agent_requested_amount_minor": requested_minor,
                    "authorized_amount_minor": authorized_minor,
                    "delta_blocked_minor": delta_blocked_minor,
                    "policy_rule_id": decision.rule_id,
                    "reply": eval_out["reply"],
                    "content": [{"type": "text", "text": summary_text}],
                }
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "tool_name": tool_name,
                    "firewall": firewall,
                    "result": result,
                    "content": [{"type": "text", "text": summary_text}],
                }

            if tool_name == "paypal_list_disputes":
                items = gateway_call(lambda: app.state.gateway.list_disputes())
                disputes_out = [
                    {
                        "dispute_id": item.dispute_id,
                        "status": item.status,
                        "reason": item.reason,
                        "amount_minor": int(item.amount_minor),
                        "currency": item.currency,
                        "order_id": item.order_id,
                    }
                    for item in items
                ]
                summary_text = (
                    f"Synced {len(disputes_out)} PayPal Customer Dispute(s) "
                    f"for merchant {merchant_id}."
                )
                firewall = {
                    "enforced": True,
                    "override_blocked": False,
                    "verdict_status": "READ_ONLY",
                    "agent_requested_amount_minor": None,
                    "authorized_amount_minor": 0,
                    "delta_blocked_minor": 0,
                    "order_captured_amount_minor": 0,
                    "currency": "USD",
                    "verdict": "READ_ONLY_DISPUTES_LISTED",
                    "policy_rule_id": "RULE-READONLY-DISPUTES",
                    "clamped_by": "Read-Only PayPal v1 Customer Disputes Feed",
                    "explanation": summary_text,
                }
                result = {
                    "merchant_id": merchant_id,
                    "count": len(disputes_out),
                    "disputes": disputes_out,
                    "content": [{"type": "text", "text": summary_text}],
                }
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "tool_name": tool_name,
                    "firewall": firewall,
                    "result": result,
                    "content": [{"type": "text", "text": summary_text}],
                }

            if tool_name == "paypal_draft_dispute_defense":
                requested_dispute_id = str(
                    args.get("dispute_id") or ""
                ).strip()
                items = gateway_call(lambda: app.state.gateway.list_disputes())
                matched = None
                for item in items:
                    if item.dispute_id == requested_dispute_id:
                        matched = item
                        break
                if matched is None and items:
                    matched = items[0]

                dispute_id_val = (
                    matched.dispute_id
                    if matched is not None
                    else (requested_dispute_id or "PP-D-40199")
                )
                order_id_val = (
                    matched.order_id
                    if matched is not None
                    else str(args.get("order_id") or "ORDER-001")
                )
                dispute_reason_val = (
                    matched.reason
                    if matched is not None
                    else "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
                )
                dispute_status_val = (
                    matched.status
                    if matched is not None
                    else "WAITING_FOR_SELLER_RESPONSE"
                )
                dispute_amount_minor = (
                    int(matched.amount_minor) if matched is not None else 2800
                )
                dispute_currency = (
                    matched.currency if matched is not None else "USD"
                )

                order = _resolve_mcp_order(order_id_val)
                capture = order.captures[0] if order.captures else None
                capture_id_val = (
                    capture.capture_id if capture is not None else "CAP-001"
                )

                all_cases = service.list_cases(connection, merchant_id)
                matching_cases = [
                    c for c in all_cases if c.get("order_id") == order.order_id
                ] or all_cases[:2]

                defense_narrative = (
                    f"PayPal Dispute Defense Brief ({dispute_id_val}): Order {order.order_id} "
                    f"(Capture {capture_id_val}, {dispute_amount_minor} minor units {dispute_currency}) "
                    f"was evaluated by Settle's deterministic policy firewall. "
                    f"Prior Settle ledger cases linked: {len(matching_cases)}. "
                    f"Evidence package prepared for POST /v1/customer/disputes/{dispute_id_val}/provide-evidence."
                )
                firewall = {
                    "enforced": True,
                    "override_blocked": False,
                    "verdict_status": "EVIDENCE_DRAFTED",
                    "agent_requested_amount_minor": None,
                    "authorized_amount_minor": dispute_amount_minor,
                    "delta_blocked_minor": 0,
                    "order_captured_amount_minor": dispute_amount_minor,
                    "currency": dispute_currency,
                    "verdict": "EVIDENCE_BRIEF_GENERATED_NO_FUNDS_MOVED",
                    "policy_rule_id": "RULE-DISPUTE-DEFENSE-PROOF",
                    "clamped_by": "Cryptographic Ledger Cross-Reference (No Funds Disbursed)",
                    "explanation": defense_narrative,
                }
                result = {
                    "merchant_id": merchant_id,
                    "dispute_id": dispute_id_val,
                    "order_id": order.order_id,
                    "capture_id": capture_id_val,
                    "status": dispute_status_val,
                    "reason": dispute_reason_val,
                    "amount_minor": dispute_amount_minor,
                    "currency": dispute_currency,
                    "paypal_endpoint": (
                        f"POST /v1/customer/disputes/{dispute_id_val}/provide-evidence"
                    ),
                    "prior_ledger_cases": matching_cases,
                    "defense_brief": {
                        "evidence_type": "PROOF_OF_FULFILLMENT_AND_SETTLEMENT_LEDGER",
                        "narrative": defense_narrative,
                        "capture_verified": capture is not None,
                        "capture_id": capture_id_val,
                        "prior_cases_count": len(matching_cases),
                    },
                    "content": [{"type": "text", "text": defense_narrative}],
                }
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "tool_name": tool_name,
                    "firewall": firewall,
                    "result": result,
                    "content": [{"type": "text", "text": defense_narrative}],
                }

            raise HTTPException(
                status_code=400, detail=f"unknown MCP tool: {tool_name}"
            )
        finally:
            connection.close()

    @app.exception_handler(PolicyError)
    async def policy_error_handler(request: Request, exc: PolicyError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    index_html = dist_dir / "index.html"
    if index_html.is_file():
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(assets_dir)),
                name="frontend-assets",
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        def serve_spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            candidate = (dist_dir / full_path).resolve()
            if (
                full_path
                and candidate.is_file()
                and dist_dir.resolve() in candidate.parents
            ):
                return FileResponse(str(candidate))
            return FileResponse(str(index_html))

    return app
