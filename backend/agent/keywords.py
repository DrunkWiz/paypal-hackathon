"""Deterministic keyword classifier — the last rung that always answers.

It is intentionally dumb and legible. Its only job is to produce a ``Case``:
a category, a sentiment, what the customer wants, and some facts. It never
produces a number that could be executed, because ``Case`` has no amount field.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from contracts import Case, Category, Order, Sentiment, Wants

__all__ = ["classify_keywords", "detect_category", "detect_sentiment", "detect_wants"]

# Ordered: earlier entries win a tie. Billing before content complaints,
# "changed mind" last so "I don't want it, it arrived broken" reads as damaged.
_CATEGORY_PATTERNS: List[Tuple[Category, Tuple[str, ...]]] = [
    (
        Category.billing_error,
        (
            "charged twice",
            "double charged",
            "duplicate charge",
            "overcharged",
            "billing error",
            "wrong amount charged",
            "two charges",
            "bayar dua kali",
            "caj dua kali",
        ),
    ),
    (
        Category.not_received,
        (
            "never arrived",
            "not received",
            "didn't arrive",
            "did not arrive",
            "hasn't arrived",
            "has not arrived",
            "no package",
            "nothing arrived",
            "not delivered",
            "never got",
            "没收到",
            "没有收到",
            "tidak sampai",
            "tak sampai",
            "belum terima",
        ),
    ),
    (
        Category.wrong_item,
        (
            "wrong item",
            "wrong product",
            "different item",
            "not what i ordered",
            "sent the wrong",
            "incorrect item",
            "salah barang",
            "barang salah",
        ),
    ),
    (
        Category.damaged,
        (
            "broken",
            "cracked",
            "damaged",
            "smashed",
            "chipped",
            "dented",
            "arrived broken",
            "in pieces",
            "坏了",
            "破了",
            "碎了",
            "rosak",
            "pecah",
        ),
    ),
    (
        Category.not_as_described,
        (
            "not as described",
            "doesn't match",
            "does not match",
            "looks different",
            "different colour",
            "different color",
            "smaller than",
            "bigger than",
            "not the colour",
            "not the color",
            "和图片不一样",
            "跟图片不一样",
        ),
    ),
    (
        Category.late,
        (
            "late",
            "delayed",
            "still waiting",
            "took too long",
            "took forever",
            "slow delivery",
            "very slow",
            "迟到",
            "很慢",
            "太慢",
            "lambat",
        ),
    ),
    (
        Category.changed_mind,
        (
            "changed my mind",
            "don't want it",
            "do not want it",
            "no longer want",
            "don't need it",
            "dont need it",
            "changed mind",
            "tak nak",
            "tidak mahu",
        ),
    ),
]

_ANGRY = (
    "furious",
    "unacceptable",
    "ridiculous",
    "disgusting",
    "terrible",
    "worst",
    "scam",
    "outrageous",
    "appalling",
)
_DISTRESSED = ("distressed", "devastated", "heartbroken", "crying", "awful", "miserable")
_FRUSTRATED = ("frustrated", "annoyed", "disappointed", "again", "still waiting", "so slow")
_CALM = ("please", "thank you", "thanks", "no rush", "whenever")

_REFUND = ("refund", "money back", "reimburse", "return my money", "退款", "pulangkan duit", "pulang duit")
_REPLACEMENT = ("replace", "replacement", "exchange", "send another", "another one", "换", "ganti")
_INFO = ("where is", "status", "tracking", "when will", "what happened", "any update", "where's")

_QUANTITY_RE = re.compile(r"(\d+)\s*(?:x\s*)?(?:items?|pieces?|units?|mugs?|cups?|个|件)\b", re.IGNORECASE)
_DELAY_RE = re.compile(r"(\d+)\s*days?\s*(?:late|delay|overdue)", re.IGNORECASE)


def _count_matches(haystack: str, needles: Tuple[str, ...]) -> int:
    return sum(1 for needle in needles if needle in haystack)


def detect_category(text: str) -> Tuple[Category, int]:
    """Return the best category and the number of phrase hits behind it."""
    lowered = text.lower()
    best = Category.other
    best_score = 0
    for category, needles in _CATEGORY_PATTERNS:
        score = _count_matches(lowered, needles)
        if score > best_score:
            best = category
            best_score = score
    return best, best_score


def detect_sentiment(text: str) -> Sentiment:
    lowered = text.lower()
    letters = [char for char in text if char.isalpha()]
    shouty = bool(letters) and sum(1 for c in letters if c.isupper()) >= max(
        8, int(len(letters) * 0.7)
    )

    angry = _count_matches(lowered, _ANGRY) + lowered.count("!!")
    if shouty:
        angry += 2
    if angry >= 1:
        return Sentiment.angry

    if _count_matches(lowered, _DISTRESSED) >= 1:
        return Sentiment.distressed
    if _count_matches(lowered, _FRUSTRATED) >= 1:
        return Sentiment.frustrated
    if _count_matches(lowered, _CALM) >= 1:
        return Sentiment.calm
    return Sentiment.neutral


def detect_wants(text: str) -> Wants:
    lowered = text.lower()
    if _count_matches(lowered, _REFUND) >= 1:
        return Wants.refund
    if _count_matches(lowered, _REPLACEMENT) >= 1:
        return Wants.replacement
    if _count_matches(lowered, _INFO) >= 1:
        return Wants.info
    return Wants.unknown


def _facts(text: str, order: Optional[Order], has_photo: bool) -> Dict[str, object]:
    facts: Dict[str, object] = {"photo_provided": bool(has_photo)}
    quantity = _QUANTITY_RE.search(text)
    if quantity:
        facts["quantity_affected"] = int(quantity.group(1))
    delay = _DELAY_RE.search(text)
    if delay:
        facts["delivery_delay_days"] = int(delay.group(1))
    if order is not None and order.items:
        facts["item_mentioned"] = order.items[0].name
    return facts


def classify_keywords(
    text: str,
    order: Optional[Order] = None,
    has_photo: bool = False,
) -> Case:
    """Classify a complaint with no model at all."""
    category, score = detect_category(text)
    if score == 0:
        confidence = 0.2
    else:
        confidence = min(0.95, 0.5 + 0.15 * score)

    capture_id = ""
    order_id = ""
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
        category=category,
        facts=_facts(text, order, has_photo),  # type: ignore[arg-type]
        sentiment=detect_sentiment(text),
        wants=detect_wants(text),
        confidence=confidence,
        raw_text=text,
    )
