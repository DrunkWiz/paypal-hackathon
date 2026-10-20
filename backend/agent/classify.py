"""Classification: strict JSON, exactly one repair retry, keyword last resort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from contracts import Case, Order, ProviderError, ProviderInvalidOutput

from .chain import FallbackChain
from .keywords import classify_keywords
from .prompts import (
    SYSTEM_CLASSIFY,
    classify_input,
    parse_json_object,
    repair_input,
    validate_classification,
)

__all__ = ["ClassificationOutcome", "classify_with_meta"]


@dataclass(frozen=True)
class ClassificationOutcome:
    case: Case
    provider: str
    model: str
    rung: int


def _build_case(
    data: Any, text: str, order: Optional[Order], has_photo: bool
) -> Case:
    facts = dict(data["facts"])
    if has_photo:
        facts["photo_provided"] = True

    order_id = ""
    capture_id = ""
    customer_email = ""
    if order is not None:
        order_id = order.order_id
        customer_email = order.payer_email
        if order.captures:
            capture_id = order.captures[0].capture_id

    return Case(
        order_id=order_id,
        capture_id=capture_id,
        customer_email=customer_email,
        category=data["category"],
        facts=facts,
        sentiment=data["sentiment"],
        wants=data["wants"],
        confidence=data["confidence"],
        raw_text=text,
    )


def classify_with_meta(
    text: str,
    order: Optional[Order],
    chain: FallbackChain,
    has_photo: bool = False,
) -> ClassificationOutcome:
    """Classify with the chain; on invalid JSON retry exactly once, then keywords."""
    user = classify_input(text, order, has_photo)
    repaired = False

    try:
        while True:
            result = chain.complete(SYSTEM_CLASSIFY, user)
            try:
                data = validate_classification(parse_json_object(result.value))
            except ProviderInvalidOutput as exc:
                if repaired:
                    raise
                repaired = True
                user = repair_input(
                    text, order, result.value, str(exc), has_photo
                )
                continue
            return ClassificationOutcome(
                case=_build_case(data, text, order, has_photo),
                provider=result.provider,
                model=result.model,
                rung=result.rung,
            )
    except ProviderError:
        # Last rung: deterministic keywords. No network, no model, no money.
        return ClassificationOutcome(
            case=classify_keywords(text, order, has_photo),
            provider="keywords",
            model="keyword-v1",
            rung=chain.size,
        )
