"""Reply writing with a hard amount post-check and a template fallback.

This is the last place a model's words meet a customer. The check is blunt on
purpose: if the text contains any currency amount that is not the decision
amount, or any percentage that is not the decision percentage, it is rejected.
"""

from __future__ import annotations

import re
from typing import List

from contracts import Action, Case, Decision, ProviderError

from .chain import FallbackChain
from .prompts import SYSTEM_REPLY, reply_input, reply_repair_input

__all__ = [
    "write_reply",
    "template_reply",
    "extract_amounts",
    "extract_percents",
    "reply_matches_decision",
]

_CURRENCY = r"(?:USD|SGD|MYR|EUR|GBP|AUD|CAD|JPY|RM|S\$|\$|\u20ac|\u00a3)"
_AMOUNT_RE = re.compile(
    _CURRENCY
    + r"\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
    + r"|([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*"
    + _CURRENCY,
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")


def extract_amounts(text: str) -> List[int]:
    """Every currency amount in ``text``, as integer minor units."""
    from backend.paypal.money import to_minor

    amounts: List[int] = []
    for match in _AMOUNT_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2)
        if not raw:
            continue
        try:
            amounts.append(to_minor(raw.replace(",", "")))
        except (ValueError, TypeError):
            continue
    return amounts


def extract_percents(text: str) -> List[float]:
    return [float(match.group(1)) for match in _PERCENT_RE.finditer(text or "")]


def reply_matches_decision(text: str, decision: Decision) -> bool:
    """True only when every money/percentage claim in ``text`` agrees."""
    amounts = extract_amounts(text)
    if decision.amount_minor > 0:
        if not amounts:
            return False
        if any(amount != decision.amount_minor for amount in amounts):
            return False
    elif amounts:
        # Nothing is being refunded, so the message must not mention money.
        return False

    percents = extract_percents(text)
    if decision.percent_applied is None:
        if percents:
            return False
    else:
        expected = float(decision.percent_applied)
        if any(percent != expected for percent in percents):
            return False

    return True


def template_reply(case: Case, decision: Decision) -> str:
    """A safe message built only from the decision. No model involved."""
    from backend.paypal.money import from_minor

    if decision.amount_minor > 0:
        return (
            "Thanks for letting us know, and sorry for the trouble. "
            "We've refunded %s %s to your original payment method. "
            "It usually arrives within 3-5 business days."
            % (decision.currency, from_minor(decision.amount_minor))
        )
    if decision.action == Action.replacement:
        return (
            "Thanks for letting us know, and sorry for the trouble. "
            "We'll send a replacement out to you."
        )
    return (
        "Thanks for letting us know, and sorry for the trouble. "
        "Someone from the shop will look at this and follow up with you "
        "directly. We haven't taken any money yet."
    )


def write_reply(case: Case, decision: Decision, chain: FallbackChain) -> str:
    """Ask the chain for a message, verify it, regenerate once, then template."""
    try:
        first = chain.complete(SYSTEM_REPLY, reply_input(case, decision))
    except ProviderError:
        return template_reply(case, decision)

    if reply_matches_decision(first.value, decision):
        return first.value.strip()

    try:
        second = chain.complete(
            SYSTEM_REPLY, reply_repair_input(case, decision, first.value)
        )
    except ProviderError:
        return template_reply(case, decision)

    if reply_matches_decision(second.value, decision):
        return second.value.strip()

    return template_reply(case, decision)
