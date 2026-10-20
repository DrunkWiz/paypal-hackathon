from __future__ import annotations

from enum import Enum
from typing import FrozenSet, List, Optional, TypedDict, Union
from dataclasses import dataclass


class Category(str, Enum):
    not_received = "not_received"
    late = "late"
    damaged = "damaged"
    wrong_item = "wrong_item"
    not_as_described = "not_as_described"
    changed_mind = "changed_mind"
    billing_error = "billing_error"
    other = "other"


class Sentiment(str, Enum):
    calm = "calm"
    neutral = "neutral"
    frustrated = "frustrated"
    angry = "angry"
    distressed = "distressed"


class Wants(str, Enum):
    refund = "refund"
    replacement = "replacement"
    info = "info"
    unknown = "unknown"


class CaseFacts(TypedDict, total=False):
    claimed_delivery_date: str
    item_mentioned: str
    photo_provided: bool
    quantity_affected: int
    delivery_delay_days: int
    notes: str


@dataclass(frozen=True)
class Case:
    order_id: str
    capture_id: str
    customer_email: str
    category: Category
    facts: CaseFacts
    sentiment: Sentiment
    wants: Wants
    confidence: float
    raw_text: str