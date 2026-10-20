"""Deterministic policy engine.

The design rule for Settle: *the model judges; code decides money*. Nothing in
this package may call a model, touch the network, read a clock the caller did
not supply, or use floating point. Every executed amount is produced here from
typed rules, a case, and real order/history data.
"""

from __future__ import annotations

from .engine import (
    evaluate,
    order_age_days,
    rule_amount,
    rule_matches,
    specificity,
)

__all__ = [
    "evaluate",
    "order_age_days",
    "rule_amount",
    "rule_matches",
    "specificity",
]
