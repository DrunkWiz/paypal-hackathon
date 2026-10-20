"""Pure evaluation of a merchant policy against a case and an order.

Guarantees this module makes, and the invariant suite enforces:

* No executed amount ever exceeds the remaining refundable balance, the
  per-refund cap, or the remaining daily budget.
* Breaching a cap produces ``needs_approval=True`` and a clamped (never larger)
  amount. It never produces a bigger number.
* An order past the merchant's age window is never refunded automatically.
* Same input (including ``now``) produces the same ``Decision`` every time.
* Raising a cap never lowers the amount.
* Integer minor units only. No floats anywhere in the money path.

The order of operations is deliberately: match -> specificity -> tie-break on
lower amount -> clamp to hard caps. Specificity chooses *which* rule the
merchant meant; the caps are the absolute ceiling that no rule can override.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence, Tuple

from contracts import (
    Action,
    Caps,
    Case,
    Decision,
    History,
    OrderSnapshot,
    Rule,
)

__all__ = [
    "evaluate",
    "order_age_days",
    "rule_amount",
    "rule_matches",
    "specificity",
]

# The optional rule bounds that make a rule "more specific" when set. Category
# narrowing is scored separately because it is a set, not a scalar bound.
_BOUND_FIELDS: Tuple[str, ...] = (
    "max_percent",
    "max_amount_minor",
    "min_order_value_minor",
    "max_order_value_minor",
    "max_order_age_days",
)

_MONEY_ACTIONS = (Action.refund_partial, Action.refund_full)


def _as_utc(value: datetime) -> datetime:
    """Normalise a datetime so naive and aware values can be compared."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def order_age_days(created_at: datetime, now: Optional[datetime] = None) -> int:
    """Whole days between ``created_at`` and ``now``, floored at zero.

    ``now`` defaults to the wall clock only so callers have a convenient
    default; every test passes an explicit value to stay deterministic.
    """
    reference = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    delta = reference - _as_utc(created_at)
    return delta.days if delta.days > 0 else 0


def specificity(rule: Rule) -> Tuple[int, int]:
    """A sort key where a larger tuple means a more specific rule.

    Primary: how many optional constraints are set (more constraints = more
    specific). Secondary: narrower category sets are more specific, encoded as
    a negative length so it sorts the same direction as the primary key.
    """
    constraints = 0
    for name in _BOUND_FIELDS:
        if getattr(rule, name) is not None:
            constraints += 1
    if rule.requires_photo:
        constraints += 1
    return (constraints, -len(rule.categories))


def rule_matches(
    rule: Rule,
    case: Case,
    order: OrderSnapshot,
    now: Optional[datetime] = None,
) -> bool:
    """True when ``rule`` applies to this case/order pair."""
    if case.category not in rule.categories:
        return False
    if (
        rule.min_order_value_minor is not None
        and order.captured_amount_minor < rule.min_order_value_minor
    ):
        return False
    if (
        rule.max_order_value_minor is not None
        and order.captured_amount_minor > rule.max_order_value_minor
    ):
        return False
    if rule.max_order_age_days is not None:
        if order_age_days(order.created_at, now) > rule.max_order_age_days:
            return False
    if rule.requires_photo and not bool(case.facts.get("photo_provided", False)):
        return False
    return True


def rule_amount(rule: Rule, order: OrderSnapshot) -> int:
    """The amount this rule authorises *before* the absolute caps are applied.

    Always a non-negative integer. ``refund_full`` uses the remaining refundable
    balance; ``refund_partial`` is the tightest of the percent bound, the fixed
    bound, and the remaining balance. Non-monetary actions are always zero.
    """
    remaining = order.captured_amount_minor - order.refunded_amount_minor
    if remaining < 0:
        remaining = 0

    if rule.action == Action.refund_full:
        return remaining

    if rule.action == Action.refund_partial:
        candidates: List[int] = [remaining]
        if rule.max_percent is not None:
            percent = rule.max_percent if rule.max_percent > 0 else 0
            candidates.append(order.captured_amount_minor * percent // 100)
        if rule.max_amount_minor is not None:
            candidates.append(rule.max_amount_minor if rule.max_amount_minor > 0 else 0)
        return max(0, min(candidates))

    return 0


def _no_match(reason: str, currency: str) -> Decision:
    return Decision(
        action=Action.handoff_to_merchant,
        amount_minor=0,
        currency=currency,
        rule_id=None,
        reason=reason,
        needs_approval=True,
        percent_applied=None,
    )


def evaluate(
    case: Case,
    order: OrderSnapshot,
    rules: Sequence[Rule],
    caps: Caps,
    history: History,
    now: Optional[datetime] = None,
) -> Decision:
    """Decide what Settle may do for ``case`` on ``order``.

    Pure. No I/O, no model, no ambient clock unless ``now`` is omitted.
    """
    # A currency mismatch is never silently computed across currencies.
    if order.currency != caps.currency:
        return _no_match(
            "currency mismatch: order is %s but caps are %s"
            % (order.currency, caps.currency),
            caps.currency,
        )

    matching = [rule for rule in rules if rule_matches(rule, case, order, now)]
    if not matching:
        return _no_match("no policy rule matched this case", caps.currency)

    # Most specific rule wins.
    best = max(specificity(rule) for rule in matching)
    finalists = [rule for rule in matching if specificity(rule) == best]

    # Ties go to the lower amount, then to a stable rule_id so the result is
    # deterministic even when two rules agree on amount.
    finalists.sort(key=lambda rule: (rule_amount(rule, order), rule.rule_id))
    chosen = finalists[0]

    desired = rule_amount(chosen, order)

    remaining_refundable = order.captured_amount_minor - order.refunded_amount_minor
    if remaining_refundable < 0:
        remaining_refundable = 0
    remaining_daily = caps.daily_total_max_minor - history.today_total_minor
    if remaining_daily < 0:
        remaining_daily = 0

    ceiling = min(remaining_refundable, caps.per_refund_max_minor, remaining_daily)
    if ceiling < 0:
        ceiling = 0

    amount = desired
    needs_approval = False
    notes: List[str] = []

    if amount > ceiling:
        amount = ceiling
        needs_approval = True
        notes.append("clamped from %d to %d minor by caps" % (desired, amount))

    action = chosen.action

    # Absolute merchant window. No rule may extend it.
    age = order_age_days(order.created_at, now)
    if age > caps.max_order_age_days:
        amount = 0
        needs_approval = True
        action = Action.handoff_to_merchant
        notes.append(
            "order age %dd exceeds merchant window %dd"
            % (age, caps.max_order_age_days)
        )

    if action is Action.handoff_to_merchant or action == Action.handoff_to_merchant:
        needs_approval = True

    if chosen.action in _MONEY_ACTIONS and amount == 0 and ceiling == 0:
        needs_approval = True
        notes.append("nothing left refundable within caps")

    reason = "rule %s" % (chosen.rule_id,)
    if notes:
        reason = reason + " | " + "; ".join(notes)

    percent_applied = (
        chosen.max_percent if chosen.action == Action.refund_partial else None
    )

    return Decision(
        action=action,
        amount_minor=amount,
        currency=caps.currency,
        rule_id=chosen.rule_id,
        reason=reason,
        needs_approval=needs_approval,
        percent_applied=percent_applied,
    )
