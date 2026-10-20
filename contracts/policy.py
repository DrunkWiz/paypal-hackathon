from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import FrozenSet, List, Mapping, Optional, Tuple, Union
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .case import Category
else:
    from .case import Category


class Action(str, Enum):
    refund_partial = "refund_partial"
    refund_full = "refund_full"
    replacement = "replacement"
    handoff_to_merchant = "handoff_to_merchant"
    dispute_provide_evidence = "dispute_provide_evidence"
    dispute_accept_claim = "dispute_accept_claim"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    categories: FrozenSet["Category"]
    max_percent: Optional[int]
    max_amount_minor: Optional[int]
    min_order_value_minor: Optional[int]
    max_order_value_minor: Optional[int]
    max_order_age_days: Optional[int]
    requires_photo: bool
    action: Action
    source_text: str


@dataclass(frozen=True)
class Caps:
    per_refund_max_minor: int
    daily_total_max_minor: int
    max_order_age_days: int
    currency: str


@dataclass(frozen=True)
class Decision:
    action: Action
    amount_minor: int
    currency: str
    rule_id: Optional[str]
    reason: str
    needs_approval: bool
    percent_applied: Optional[int]


@dataclass(frozen=True)
class OrderSnapshot:
    order_id: str
    capture_id: str
    captured_amount_minor: int
    currency: str
    created_at: datetime
    refunded_amount_minor: int


@dataclass(frozen=True)
class RefundRecord:
    amount_minor: int
    created_at: datetime


@dataclass(frozen=True)
class History:
    refunds: Tuple[RefundRecord, ...]
    today_total_minor: int