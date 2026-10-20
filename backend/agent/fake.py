"""A deterministic, offline ``ModelProvider``.

It understands the prompt shapes built in ``prompts.py`` and answers from the
keyword classifier and the default policy. That makes the whole agent pipeline
testable and demo-able with no network and no API key.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Union

from contracts import (
    Capture,
    Order,
    OrderItem,
    ProviderResult,
)

from .keywords import classify_keywords
from .prompts import CLASSIFY_TAG, POLICY_TAG, REPLY_TAG, extract_input_json

__all__ = ["FakeProvider"]

_EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)

ScriptedItem = Union[str, BaseException]


def _order_from_payload(data: Dict[str, Any]) -> Optional[Order]:
    if not data:
        return None
    currency = str(data.get("currency", "USD"))
    captures = tuple(
        Capture(
            capture_id=str(item.get("capture_id", "")),
            order_id=str(data.get("order_id", "")),
            status="COMPLETED",
            amount_minor=int(item.get("amount_minor", 0)),
            currency=currency,
            refunded_amount_minor=0,
            created_at=_EPOCH,
        )
        for item in data.get("captures") or []
    )
    items = tuple(
        OrderItem(
            name=str(item.get("name", "")),
            quantity=int(item.get("quantity", 1)),
            unit_amount_minor=int(item.get("unit_amount_minor", 0)),
        )
        for item in data.get("items") or []
    )
    return Order(
        order_id=str(data.get("order_id", "")),
        status="COMPLETED",
        amount_minor=int(data.get("amount_minor", 0)),
        currency=currency,
        created_at=_EPOCH,
        payer_email=str(data.get("customer_email", "")),
        captures=captures,
        items=items,
    )


def _classification_json(text: str, order: Optional[Order], has_photo: bool) -> str:
    case = classify_keywords(text, order, has_photo)
    return json.dumps(
        {
            "category": case.category.value,
            "sentiment": case.sentiment.value,
            "wants": case.wants.value,
            "confidence": case.confidence,
            "facts": dict(case.facts),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _reply_text(decision: Dict[str, Any]) -> str:
    from backend.paypal.money import from_minor

    amount_minor = int(decision.get("amount_minor", 0) or 0)
    currency = str(decision.get("currency", "USD"))
    action = str(decision.get("action", ""))
    if amount_minor > 0:
        return (
            "Thanks for letting us know, and sorry for the trouble. "
            "We've refunded %s %s to your original payment method. "
            "It usually arrives within 3-5 business days."
            % (currency, from_minor(amount_minor))
        )
    if action == "replacement":
        return (
            "Thanks for letting us know, and sorry for the trouble. "
            "We'll send a replacement out to you."
        )
    return (
        "Thanks for letting us know, and sorry for the trouble. "
        "Someone from the shop will look at this and follow up with you "
        "directly. We haven't taken any money yet."
    )


class FakeProvider:
    """Deterministic provider. Scripted responses take priority over defaults."""

    def __init__(
        self,
        model: str = "fake-1",
        scripted: Optional[Sequence[ScriptedItem]] = None,
        name: str = "fake",
    ) -> None:
        self._model = model
        self._name = name
        self._scripted: List[ScriptedItem] = list(scripted or [])
        self.calls: List[Any] = []

    @property
    def name(self) -> str:
        return self._name

    def push(self, item: ScriptedItem) -> None:
        self._scripted.append(item)

    def complete(self, system: str, user: str) -> ProviderResult[str]:
        self.calls.append((system, user))
        if self._scripted:
            item = self._scripted.pop(0)
            if isinstance(item, BaseException):
                raise item
            return ProviderResult(
                value=item, provider=self._name, model=self._model, rung=0
            )
        return ProviderResult(
            value=self._default(system, user),
            provider=self._name,
            model=self._model,
            rung=0,
        )

    def _default(self, system: str, user: str) -> str:
        if CLASSIFY_TAG in system:
            payload = extract_input_json(user)
            order = _order_from_payload(payload.get("order") or {})
            return _classification_json(
                str(payload.get("text", "")),
                order,
                bool(payload.get("has_photo", False)),
            )

        if POLICY_TAG in system:
            from .policy import default_policy, rule_to_json

            return json.dumps(
                {"rules": [rule_to_json(rule) for rule in default_policy()]},
                ensure_ascii=False,
                sort_keys=True,
            )

        if REPLY_TAG in system:
            payload = extract_input_json(user)
            return _reply_text(payload.get("decision") or {})

        return "{}"
