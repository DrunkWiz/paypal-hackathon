"""FastAPI application: onboarding, policy, resolve, execute, dashboard."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from contracts import (
    Caps,
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

    @app.get("/api/resolve/{token}")
    def resolve_get(token: str) -> Dict[str, Any]:
        payload = verify(token)
        order = gateway_call(
            lambda: app.state.gateway.get_order(payload["order_id"])
        )
        capture = order.captures[0] if order.captures else None
        return {
            "merchant_id": payload["merchant_id"],
            "order_id": order.order_id,
            "status": order.status,
            "currency": order.currency,
            "amount_minor": order.amount_minor,
            "items": [
                {"name": item.name, "quantity": item.quantity}
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
            return service.execute_refund(
                connection,
                app.state.gateway,
                payload["merchant_id"],
                case_row,
                decision_row,
                app.state.now(),
            )
        finally:
            connection.close()

    @app.post("/api/resolve/{token}/decline")
    def resolve_decline(token: str, body: AcceptIn) -> Dict[str, Any]:
        payload = verify(token)
        connection = conn()
        try:
            case_row = service.get_case_row(connection, body.case_id)
            if case_row["order_id"] != payload["order_id"]:
                raise HTTPException(
                    status_code=403,
                    detail="case does not belong to this resolution token",
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

    @app.exception_handler(PolicyError)
    async def policy_error_handler(request: Request, exc: PolicyError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
