"""Policy compilation: typed rules, honest fallback provenance."""

from __future__ import annotations

import pytest

from backend.agent.chain import FallbackChain
from backend.agent.fake import FakeProvider
from backend.agent.policy import (
    compile_policy_with_meta,
    default_policy,
    rule_to_json,
)
from backend.agent.prompts import validate_rules
from backend.agent.provider import AgentProvider
from contracts import (
    Category,
    Provider,
    ProviderInvalidOutput,
    ProviderTimeout,
    Rule,
)


def test_default_policy_covers_all_categories():
    covered = set()
    for rule in default_policy():
        covered |= set(rule.categories)
    assert covered == set(Category)


def test_default_policy_is_typed():
    for rule in default_policy():
        assert isinstance(rule, Rule)


def test_compile_via_fake_chain():
    chain = FallbackChain([FakeProvider()])
    outcome = compile_policy_with_meta("Refunds for damaged items.", chain)
    assert outcome.provider == "fake"
    assert {rule.rule_id for rule in outcome.rules} == {
        rule.rule_id for rule in default_policy()
    }


def test_compile_falls_back_to_defaults_on_provider_failure():
    chain = FallbackChain([FakeProvider(scripted=[ProviderTimeout("down")])])
    outcome = compile_policy_with_meta("anything", chain)
    assert outcome.provider == "defaults"
    assert outcome.rung == chain.size
    assert len(outcome.rules) == len(default_policy())


def test_validate_rules_rejects_unknown_action():
    with pytest.raises(ProviderInvalidOutput):
        validate_rules(
            {
                "rules": [
                    {
                        "rule_id": "x",
                        "categories": ["damaged"],
                        "action": "give_everything_away",
                    }
                ]
            }
        )


def test_validate_rules_rejects_empty_list():
    with pytest.raises(ProviderInvalidOutput):
        validate_rules({"rules": []})


def test_validate_rules_rejects_float_money():
    with pytest.raises(ProviderInvalidOutput):
        validate_rules(
            {
                "rules": [
                    {
                        "rule_id": "x",
                        "categories": ["damaged"],
                        "action": "refund_full",
                        "max_amount_minor": 12.5,
                    }
                ]
            }
        )


def test_rule_to_json_round_trips_fields():
    rule = default_policy()[0]
    payload = rule_to_json(rule)
    assert payload["rule_id"] == rule.rule_id
    assert isinstance(payload["categories"], list)
    assert payload["action"] == rule.action.value


def test_agent_provider_satisfies_protocol():
    provider = AgentProvider(FallbackChain([FakeProvider()]))
    assert isinstance(provider, Provider) is True


def test_agent_provider_compile_policy_returns_rules():
    provider = AgentProvider(FallbackChain([FakeProvider()]))
    rules = provider.compile_policy("Damaged items get a full refund.")
    assert rules
    assert all(isinstance(rule, Rule) for rule in rules)
