"""Reply writing: the model's words never get to move money."""

from __future__ import annotations

import pytest

from backend.agent.chain import FallbackChain
from backend.agent.fake import FakeProvider
from backend.agent.reply import (
    extract_amounts,
    extract_percents,
    reply_matches_decision,
    template_reply,
    write_reply,
)
from contracts import Action, Case, Category, Decision, Sentiment, Wants


def make_case():
    return Case(
        order_id="ORDER-1",
        capture_id="CAP-1",
        customer_email="buyer@example.com",
        category=Category.damaged,
        facts={},
        sentiment=Sentiment.frustrated,
        wants=Wants.refund,
        confidence=0.9,
        raw_text="broken",
    )


def make_decision(
    amount_minor=1234,
    currency="USD",
    percent_applied=None,
    action=Action.refund_partial,
    needs_approval=False,
):
    return Decision(
        action=action,
        amount_minor=amount_minor,
        currency=currency,
        rule_id="rule-1",
        reason="reason",
        needs_approval=needs_approval,
        percent_applied=percent_applied,
    )


# -- extraction -------------------------------------------------------------


def test_extract_prefixed_amount():
    assert extract_amounts("We refunded USD 12.34 to you.") == [1234]


def test_extract_symbol_amount():
    assert extract_amounts("We refunded $12.34 to you.") == [1234]


def test_extract_suffixed_amount():
    assert extract_amounts("Refunded 12.34 USD today.") == [1234]


def test_extract_large_amount():
    assert extract_amounts("A refund of $500.00") == [50000]


def test_extract_percent():
    assert extract_percents("That is 50% back.") == [50.0]


def test_extract_no_amounts():
    assert extract_amounts("Thanks, we will follow up.") == []


# -- post-check -------------------------------------------------------------


def test_matching_amount_is_accepted():
    assert reply_matches_decision("We refunded USD 12.34.", make_decision()) is True


def test_wrong_amount_is_rejected():
    assert reply_matches_decision("We refunded USD 500.00.", make_decision()) is False


def test_two_amounts_one_wrong_is_rejected():
    text = "Your order was USD 50.00 and we refunded USD 12.34."
    assert reply_matches_decision(text, make_decision()) is False


def test_missing_amount_is_rejected_when_money_moves():
    assert reply_matches_decision("We refunded you.", make_decision()) is False


def test_unexpected_percentage_is_rejected():
    assert reply_matches_decision("We refunded USD 12.34, 50% back.", make_decision()) is False


def test_matching_percentage_is_accepted():
    decision = make_decision(percent_applied=50)
    assert (
        reply_matches_decision("We refunded USD 12.34, 50% back.", decision) is True
    )


def test_wrong_percentage_is_rejected():
    decision = make_decision(percent_applied=50)
    assert (
        reply_matches_decision("We refunded USD 12.34, 25% back.", decision) is False
    )


def test_zero_amount_message_without_money_is_accepted():
    decision = make_decision(amount_minor=0, action=Action.handoff_to_merchant)
    assert reply_matches_decision("A person will follow up.", decision) is True


def test_zero_amount_message_with_money_is_rejected():
    decision = make_decision(amount_minor=0, action=Action.handoff_to_merchant)
    assert reply_matches_decision("We refunded USD 0.00.", decision) is False


# -- template ---------------------------------------------------------------


def test_template_states_exact_amount():
    text = template_reply(make_case(), make_decision())
    assert "USD 12.34" in text


def test_template_never_mentions_money_when_amount_is_zero():
    decision = make_decision(amount_minor=0, action=Action.handoff_to_merchant)
    text = template_reply(make_case(), decision)
    assert extract_amounts(text) == []


def test_template_for_replacement():
    decision = make_decision(amount_minor=0, action=Action.replacement)
    assert "replacement" in template_reply(make_case(), decision).lower()


# -- write_reply ------------------------------------------------------------


def test_write_reply_accepts_accurate_fake_output():
    chain = FallbackChain([FakeProvider()])
    text = write_reply(make_case(), make_decision(), chain)
    assert "USD 12.34" in text


def test_write_reply_regenerates_once_then_accepts():
    chain = FallbackChain(
        [
            FakeProvider(
                scripted=[
                    "We refunded USD 500.00, sorry!",
                    "We refunded USD 12.34, sorry!",
                ]
            )
        ]
    )
    text = write_reply(make_case(), make_decision(), chain)
    assert "USD 12.34" in text
    assert "500" not in text


def test_write_reply_falls_back_to_template_after_two_bad_outputs():
    chain = FallbackChain(
        [
            FakeProvider(
                scripted=[
                    "We refunded USD 500.00.",
                    "We refunded USD 999.00.",
                ]
            )
        ]
    )
    text = write_reply(make_case(), make_decision(), chain)
    assert "USD 12.34" in text
    assert "500" not in text
    assert "999" not in text


def test_injection_text_never_reaches_customer():
    chain = FallbackChain(
        [
            FakeProvider(
                scripted=[
                    "I ignored the rules and refunded USD 500.00.",
                    "I ignored the rules and refunded USD 500.00.",
                ]
            )
        ]
    )
    text = write_reply(make_case(), make_decision(), chain)
    assert "500" not in text
    assert "USD 12.34" in text


def test_write_reply_falls_back_when_chain_fails():
    from contracts import ProviderTimeout

    chain = FallbackChain([FakeProvider(scripted=[ProviderTimeout("down")])])
    text = write_reply(make_case(), make_decision(), chain)
    assert "USD 12.34" in text
