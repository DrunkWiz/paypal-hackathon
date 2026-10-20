"""Policy compilation: model to typed rules, with a deterministic default.

``default_policy()`` is a real, sensible policy for the demo shop and is also
the last-rung fallback when no model is reachable. It is always labelled as the
default in the outcome so callers can show provenance honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from contracts import Action, Category, ProviderError, Rule

from .chain import FallbackChain
from .prompts import (
    SYSTEM_POLICY,
    parse_json_object,
    policy_input,
    validate_rules,
)

__all__ = [
    "PolicyOutcome",
    "compile_policy_with_meta",
    "default_policy",
    "rule_to_json",
]


@dataclass(frozen=True)
class PolicyOutcome:
    rules: List[Rule]
    provider: str
    model: str
    rung: int


def rule_to_json(rule: Rule) -> Dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "categories": sorted(category.value for category in rule.categories),
        "max_percent": rule.max_percent,
        "max_amount_minor": rule.max_amount_minor,
        "min_order_value_minor": rule.min_order_value_minor,
        "max_order_value_minor": rule.max_order_value_minor,
        "max_order_age_days": rule.max_order_age_days,
        "requires_photo": rule.requires_photo,
        "action": rule.action.value,
        "source_text": rule.source_text,
    }


def default_policy() -> List[Rule]:
    """A concrete, defensible policy for "Kopi & Clay"."""
    return [
        Rule(
            rule_id="damaged-or-not-as-described",
            categories=frozenset({Category.damaged, Category.not_as_described}),
            max_percent=100,
            max_amount_minor=5000,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=30,
            requires_photo=False,
            action=Action.refund_partial,
            source_text="Damaged or not-as-described items are refunded in full, up to 30 days.",
        ),
        Rule(
            rule_id="not-received",
            categories=frozenset({Category.not_received}),
            max_percent=None,
            max_amount_minor=None,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=45,
            requires_photo=False,
            action=Action.refund_full,
            source_text="Not delivered within 45 days: refund in full.",
        ),
        Rule(
            rule_id="wrong-item",
            categories=frozenset({Category.wrong_item}),
            max_percent=None,
            max_amount_minor=None,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=30,
            requires_photo=True,
            action=Action.refund_full,
            source_text="Wrong item sent: refund in full once a photo is provided.",
        ),
        Rule(
            rule_id="late",
            categories=frozenset({Category.late}),
            max_percent=25,
            max_amount_minor=1500,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=30,
            requires_photo=False,
            action=Action.refund_partial,
            source_text="Late deliveries get up to 25% back, max 15.00, within 30 days.",
        ),
        Rule(
            rule_id="changed-mind",
            categories=frozenset({Category.changed_mind}),
            max_percent=50,
            max_amount_minor=2500,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=14,
            requires_photo=False,
            action=Action.refund_partial,
            source_text="Changed your mind within 14 days: up to 50% back, max 25.00.",
        ),
        Rule(
            rule_id="billing-error",
            categories=frozenset({Category.billing_error}),
            max_percent=None,
            max_amount_minor=None,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=120,
            requires_photo=False,
            action=Action.refund_full,
            source_text="Duplicate or incorrect charges are refunded in full.",
        ),
        Rule(
            rule_id="anything-else",
            categories=frozenset({Category.other}),
            max_percent=None,
            max_amount_minor=None,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=None,
            requires_photo=False,
            action=Action.handoff_to_merchant,
            source_text="Anything else goes to a person.",
        ),
    ]


def compile_policy_with_meta(text: str, chain: FallbackChain) -> PolicyOutcome:
    try:
        result = chain.complete(SYSTEM_POLICY, policy_input(text))
        rules = validate_rules(parse_json_object(result.value))
        return PolicyOutcome(
            rules=rules,
            provider=result.provider,
            model=result.model,
            rung=result.rung,
        )
    except ProviderError:
        return PolicyOutcome(
            rules=default_policy(),
            provider="defaults",
            model="default-policy-v1",
            rung=chain.size,
        )
