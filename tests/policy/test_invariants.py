"""Invariants for the deterministic policy engine.

These are the tests that matter most: they are the reason a model's text can
never move money. If any of these fail, the product's central claim is false.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from backend.policy import (
    evaluate,
    order_age_days,
    rule_amount,
    rule_matches,
    specificity,
)
from contracts import (
    Action,
    Caps,
    Case,
    Category,
    History,
    OrderSnapshot,
    Rule,
    Sentiment,
    Wants,
)

NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_case(category=Category.damaged, photo=False, facts=None):
    if facts is None:
        facts = {"photo_provided": photo}
    return Case(
        order_id="ORDER-1",
        capture_id="CAPTURE-1",
        customer_email="buyer@example.com",
        category=category,
        facts=facts,
        sentiment=Sentiment.neutral,
        wants=Wants.refund,
        confidence=0.8,
        raw_text="something went wrong",
    )


def make_order(captured=5000, refunded=0, age_days=10, currency="USD"):
    return OrderSnapshot(
        order_id="ORDER-1",
        capture_id="CAPTURE-1",
        captured_amount_minor=captured,
        currency=currency,
        created_at=NOW - timedelta(days=age_days),
        refunded_amount_minor=refunded,
    )


def make_rule(
    rule_id="r1",
    categories=(Category.damaged,),
    action=Action.refund_partial,
    max_percent=None,
    max_amount_minor=None,
    min_order_value_minor=None,
    max_order_value_minor=None,
    max_order_age_days=None,
    requires_photo=False,
):
    return Rule(
        rule_id=rule_id,
        categories=frozenset(categories),
        max_percent=max_percent,
        max_amount_minor=max_amount_minor,
        min_order_value_minor=min_order_value_minor,
        max_order_value_minor=max_order_value_minor,
        max_order_age_days=max_order_age_days,
        requires_photo=requires_photo,
        action=action,
        source_text="source",
    )


def make_caps(per_refund=5000, daily=20000, age=90, currency="USD"):
    return Caps(
        per_refund_max_minor=per_refund,
        daily_total_max_minor=daily,
        max_order_age_days=age,
        currency=currency,
    )


def make_history(today_total=0):
    return History(refunds=(), today_total_minor=today_total)


def random_rule(rng, index):
    return Rule(
        rule_id="r%d" % index,
        categories=frozenset(rng.sample(list(Category), rng.randrange(1, 4))),
        max_percent=rng.choice([None, 0, 5, 10, 25, 50, 100]),
        max_amount_minor=rng.choice([None, 0, 100, 500, 1000, 10000]),
        min_order_value_minor=rng.choice([None, 0, 1000, 5000]),
        max_order_value_minor=rng.choice([None, 1000, 5000, 100000]),
        max_order_age_days=rng.choice([None, 1, 7, 30, 90, 365]),
        requires_photo=rng.random() < 0.3,
        action=rng.choice(
            [
                Action.refund_partial,
                Action.refund_full,
                Action.replacement,
                Action.handoff_to_merchant,
            ]
        ),
        source_text="generated",
    )


# ---------------------------------------------------------------------------
# Core invariants (randomised)
# ---------------------------------------------------------------------------


def test_invariants_hold_over_random_inputs():
    rng = random.Random(20240601)
    for _ in range(1000):
        caps = Caps(
            per_refund_max_minor=rng.randrange(0, 20000),
            daily_total_max_minor=rng.randrange(0, 50000),
            max_order_age_days=rng.choice([0, 1, 7, 30, 90, 365]),
            currency="USD",
        )
        today_total = rng.randrange(0, caps.daily_total_max_minor + 1)
        history = History(refunds=(), today_total_minor=today_total)

        captured = rng.randrange(0, 50000)
        refunded = rng.randrange(0, captured + 1) if captured else 0
        order = make_order(
            captured=captured,
            refunded=refunded,
            age_days=rng.randrange(0, 400),
        )
        case = make_case(
            category=rng.choice(list(Category)),
            photo=rng.random() < 0.5,
        )
        rules = [random_rule(rng, i) for i in range(rng.randrange(0, 6))]

        decision = evaluate(case, order, rules, caps, history, now=NOW)

        remaining_refundable = max(0, captured - refunded)
        remaining_daily = max(0, caps.daily_total_max_minor - today_total)

        assert isinstance(decision.amount_minor, int)
        assert not isinstance(decision.amount_minor, bool)
        assert decision.amount_minor >= 0
        assert decision.amount_minor <= remaining_refundable
        assert decision.amount_minor <= caps.per_refund_max_minor
        assert decision.amount_minor <= remaining_daily
        assert decision.currency == caps.currency


def test_determinism_same_input_same_output():
    case = make_case(Category.damaged, photo=True)
    order = make_order(captured=4321, refunded=321, age_days=12)
    rules = [
        make_rule("a", max_percent=25),
        make_rule("b", max_amount_minor=1000, requires_photo=True),
        make_rule("c", action=Action.refund_full),
    ]
    caps = make_caps(per_refund=2000, daily=9000, age=60)
    history = make_history(today_total=1500)

    first = evaluate(case, order, rules, caps, history, now=NOW)
    for _ in range(20):
        again = evaluate(case, order, rules, caps, history, now=NOW)
        assert again == first


def test_monotonicity_raising_caps_never_lowers_amount():
    rng = random.Random(777)
    for _ in range(500):
        caps = Caps(
            per_refund_max_minor=rng.randrange(0, 20000),
            daily_total_max_minor=rng.randrange(0, 50000),
            max_order_age_days=rng.choice([0, 1, 7, 30, 90, 365]),
            currency="USD",
        )
        today_total = rng.randrange(0, caps.daily_total_max_minor + 1)
        history = History(refunds=(), today_total_minor=today_total)
        captured = rng.randrange(0, 50000)
        refunded = rng.randrange(0, captured + 1) if captured else 0
        order = make_order(captured=captured, refunded=refunded, age_days=rng.randrange(0, 400))
        case = make_case(category=rng.choice(list(Category)), photo=rng.random() < 0.5)
        rules = [random_rule(rng, i) for i in range(rng.randrange(1, 5))]

        before = evaluate(case, order, rules, caps, history, now=NOW)

        raised_caps = Caps(
            per_refund_max_minor=caps.per_refund_max_minor + rng.randrange(0, 20000),
            daily_total_max_minor=caps.daily_total_max_minor + rng.randrange(0, 20000),
            max_order_age_days=caps.max_order_age_days + rng.randrange(0, 365),
            currency="USD",
        )
        after = evaluate(case, order, rules, raised_caps, history, now=NOW)

        assert after.amount_minor >= before.amount_minor


# ---------------------------------------------------------------------------
# Hard caps
# ---------------------------------------------------------------------------


def test_per_refund_cap_clamps_and_requests_approval():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=5000),
        rules=[make_rule(action=Action.refund_full)],
        caps=make_caps(per_refund=1000, daily=100000, age=365),
        history=make_history(),
        now=NOW,
    )
    assert decision.amount_minor == 1000
    assert decision.needs_approval is True
    assert "clamped" in decision.reason


def test_daily_budget_clamps():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=5000),
        rules=[make_rule(action=Action.refund_full)],
        caps=make_caps(per_refund=100000, daily=2000, age=365),
        history=make_history(today_total=1500),
        now=NOW,
    )
    assert decision.amount_minor == 500
    assert decision.needs_approval is True


def test_never_exceeds_remaining_refundable():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=1000, refunded=900),
        rules=[make_rule(action=Action.refund_full)],
        caps=make_caps(per_refund=100000, daily=100000, age=365),
        history=make_history(),
        now=NOW,
    )
    assert decision.amount_minor == 100


def test_exhausted_daily_budget_refunds_nothing():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=5000),
        rules=[make_rule(action=Action.refund_full)],
        caps=make_caps(per_refund=100000, daily=2000, age=365),
        history=make_history(today_total=2000),
        now=NOW,
    )
    assert decision.amount_minor == 0
    assert decision.needs_approval is True


def test_order_outside_merchant_window_cannot_be_refunded():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=5000, age_days=60),
        rules=[make_rule(action=Action.refund_full, max_order_age_days=90)],
        caps=make_caps(per_refund=5000, daily=20000, age=30),
        history=make_history(),
        now=NOW,
    )
    assert decision.amount_minor == 0
    assert decision.needs_approval is True
    assert decision.action == Action.handoff_to_merchant


def test_currency_mismatch_never_computes_money():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=5000, currency="EUR"),
        rules=[make_rule(action=Action.refund_full)],
        caps=make_caps(currency="USD"),
        history=make_history(),
        now=NOW,
    )
    assert decision.amount_minor == 0
    assert decision.currency == "USD"
    assert decision.needs_approval is True


# ---------------------------------------------------------------------------
# Rule selection
# ---------------------------------------------------------------------------


def test_no_matching_rule_hands_off_to_merchant():
    decision = evaluate(
        case=make_case(Category.changed_mind),
        order=make_order(),
        rules=[make_rule(categories=(Category.damaged,))],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.action == Action.handoff_to_merchant
    assert decision.amount_minor == 0
    assert decision.needs_approval is True
    assert decision.rule_id is None


def test_empty_rules_hands_off():
    decision = evaluate(
        case=make_case(),
        order=make_order(),
        rules=[],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.action == Action.handoff_to_merchant
    assert decision.rule_id is None


def test_more_specific_rule_wins_even_at_lower_amount():
    loose = make_rule("loose", max_percent=50)
    tight = make_rule("tight", max_percent=10, requires_photo=True)
    decision = evaluate(
        case=make_case(photo=True),
        order=make_order(captured=1000),
        rules=[loose, tight],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.rule_id == "tight"
    assert decision.amount_minor == 100


def test_narrower_category_set_wins_on_specificity_tie():
    broad = make_rule("broad", categories=(Category.damaged, Category.late), max_percent=50)
    narrow = make_rule("narrow", categories=(Category.damaged,), max_percent=50)
    decision = evaluate(
        case=make_case(Category.damaged),
        order=make_order(captured=1000),
        rules=[broad, narrow],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.rule_id == "narrow"


def test_equal_specificity_tie_goes_to_lower_amount():
    expensive = make_rule("expensive", max_amount_minor=1000)
    cheap = make_rule("cheap", max_percent=10)
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=1000),
        rules=[expensive, cheap],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert specificity(expensive) == specificity(cheap)
    assert decision.rule_id == "cheap"
    assert decision.amount_minor == 100


def test_requires_photo_rule_is_skipped_without_photo():
    photo_rule = make_rule("photo", requires_photo=True, action=Action.refund_full)
    fallback = make_rule("fallback", max_amount_minor=100)
    decision = evaluate(
        case=make_case(photo=False),
        order=make_order(captured=5000),
        rules=[photo_rule, fallback],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.rule_id == "fallback"
    assert decision.amount_minor == 100


def test_order_value_bounds_filter_rules():
    below_min = make_rule("below_min", min_order_value_minor=5000, action=Action.refund_full)
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=1000),
        rules=[below_min],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.rule_id is None


# ---------------------------------------------------------------------------
# Arithmetic shape
# ---------------------------------------------------------------------------


def test_percent_math_floors_with_integers():
    rule = make_rule(max_percent=33)
    assert rule_amount(rule, make_order(captured=999)) == 999 * 33 // 100
    assert rule_amount(rule, make_order(captured=999)) == 329


def test_refund_partial_takes_tightest_bound():
    rule = make_rule(max_percent=50, max_amount_minor=200)
    assert rule_amount(rule, make_order(captured=1000)) == 200


def test_non_monetary_action_is_zero():
    assert rule_amount(make_rule(action=Action.replacement), make_order()) == 0
    assert rule_amount(make_rule(action=Action.handoff_to_merchant), make_order()) == 0


def test_replacement_decision_has_zero_amount():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=5000),
        rules=[make_rule(action=Action.replacement)],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.action == Action.replacement
    assert decision.amount_minor == 0


def test_percent_applied_is_reported_for_partial_rules():
    decision = evaluate(
        case=make_case(),
        order=make_order(captured=1000),
        rules=[make_rule(max_percent=25)],
        caps=make_caps(),
        history=make_history(),
        now=NOW,
    )
    assert decision.percent_applied == 25


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_order_age_days_handles_naive_and_aware():
    naive_created = datetime(2024, 5, 1, 12, 0, 0)
    assert order_age_days(naive_created, NOW) == 31
    assert order_age_days(NOW, NOW) == 0


def test_order_age_days_never_negative():
    future = NOW + timedelta(days=5)
    assert order_age_days(future, NOW) == 0


def test_rule_matches_checks_category():
    rule = make_rule(categories=(Category.damaged,))
    assert rule_matches(rule, make_case(Category.damaged), make_order(), NOW) is True
    assert rule_matches(rule, make_case(Category.late), make_order(), NOW) is False
