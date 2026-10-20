"""Conformance tests for the frozen `contracts/` package.

These tests pin the seam between the policy engine, the PayPal layer, the agent
layer, the API and the frontend. If any of them fails, something that other
layers depend on has changed shape.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from datetime import datetime

import pytest

import contracts
from contracts import (
    Action,
    Caps,
    Case,
    CaseFacts,
    Category,
    Capture,
    Decision,
    Dispute,
    DisputeAction,
    DisputeActionResult,
    GatewayTimeout,
    History,
    ModelProvider,
    NotFoundError,
    Order,
    OrderItem,
    OrderSnapshot,
    PayPalError,
    PayPalGateway,
    PayPalRejectedError,
    PayPalTransientError,
    PolicyError,
    Provider,
    ProviderError,
    ProviderInvalidOutput,
    ProviderResult,
    ProviderTimeout,
    Refund,
    RefundRecord,
    Rule,
    Sentiment,
    SettleError,
    TokenError,
    Wants,
    WebhookEvent,
)

FROZEN_DATACLASSES = [
    Case,
    Rule,
    Caps,
    Decision,
    OrderSnapshot,
    RefundRecord,
    History,
    OrderItem,
    Capture,
    Order,
    Refund,
    Dispute,
    DisputeActionResult,
    WebhookEvent,
    ProviderResult,
]

NOW = datetime(2024, 1, 1, 12, 0, 0)


def _samples():
    """One minimal valid instance of every frozen dataclass."""
    return [
        Case(
            order_id="ORDER-1",
            capture_id="CAPTURE-1",
            customer_email="buyer@example.com",
            category=Category.damaged,
            facts={},
            sentiment=Sentiment.calm,
            wants=Wants.refund,
            confidence=0.9,
            raw_text="the mug arrived cracked",
        ),
        Rule(
            rule_id="rule-1",
            categories=frozenset({Category.damaged}),
            max_percent=50,
            max_amount_minor=1000,
            min_order_value_minor=None,
            max_order_value_minor=None,
            max_order_age_days=30,
            requires_photo=False,
            action=Action.refund_partial,
            source_text="Damaged items get up to 50% back.",
        ),
        Caps(
            per_refund_max_minor=5000,
            daily_total_max_minor=20000,
            max_order_age_days=90,
            currency="USD",
        ),
        Decision(
            action=Action.refund_partial,
            amount_minor=500,
            currency="USD",
            rule_id="rule-1",
            reason="damaged, within caps",
            needs_approval=False,
            percent_applied=50,
        ),
        OrderSnapshot(
            order_id="ORDER-1",
            capture_id="CAPTURE-1",
            captured_amount_minor=1000,
            currency="USD",
            created_at=NOW,
            refunded_amount_minor=0,
        ),
        RefundRecord(amount_minor=100, created_at=NOW),
        History(refunds=(), today_total_minor=0),
        OrderItem(name="Kopi mug", quantity=1, unit_amount_minor=1000),
        Capture(
            capture_id="CAPTURE-1",
            order_id="ORDER-1",
            status="COMPLETED",
            amount_minor=1000,
            currency="USD",
            refunded_amount_minor=0,
            created_at=NOW,
        ),
        Order(
            order_id="ORDER-1",
            status="COMPLETED",
            amount_minor=1000,
            currency="USD",
            created_at=NOW,
            payer_email="buyer@example.com",
            captures=(),
            items=(),
        ),
        Refund(
            refund_id="REFUND-1",
            capture_id="CAPTURE-1",
            status="COMPLETED",
            amount_minor=100,
            currency="USD",
            created_at=NOW,
        ),
        Dispute(
            dispute_id="DISPUTE-1",
            status="OPEN",
            reason="ITEM_NOT_RECEIVED",
            amount_minor=1000,
            currency="USD",
            created_at=NOW,
            order_id="ORDER-1",
            capture_id="CAPTURE-1",
            evidence_due_by=None,
        ),
        DisputeActionResult(
            dispute_id="DISPUTE-1",
            action=DisputeAction.accept_claim,
            status="ACCEPTED",
            raw={},
        ),
        WebhookEvent(
            event_id="WH-1",
            event_type="PAYMENT.CAPTURE.REFUNDED",
            resource_type="refund",
            resource_id="REFUND-1",
            verified=True,
            payload={},
            received_at=NOW,
        ),
        ProviderResult(value="hello", provider="fake", model="fake-1", rung=0),
    ]


SAMPLES = _samples()


# ---------------------------------------------------------------------------
# 1. Import surface
# ---------------------------------------------------------------------------


EXPECTED_ALL = [
    # errors
    "SettleError",
    "PayPalError",
    "PayPalTransientError",
    "GatewayTimeout",
    "PayPalRejectedError",
    "ProviderError",
    "ProviderTimeout",
    "ProviderInvalidOutput",
    "PolicyError",
    "TokenError",
    "NotFoundError",
    # case
    "Category",
    "Sentiment",
    "Wants",
    "CaseFacts",
    "Case",
    # policy
    "Action",
    "Rule",
    "Caps",
    "Decision",
    "OrderSnapshot",
    "RefundRecord",
    "History",
    # paypal
    "DisputeAction",
    "OrderItem",
    "Capture",
    "Order",
    "Refund",
    "Dispute",
    "DisputeActionResult",
    "WebhookEvent",
    "PayPalGateway",
    # provider
    "Provider",
    "ProviderResult",
    "ModelProvider",
]


def test_package_imports():
    assert contracts is not None


def test_all_matches_expected_surface():
    assert sorted(contracts.__all__) == sorted(EXPECTED_ALL)


def test_all_has_no_duplicates():
    assert len(set(contracts.__all__)) == len(contracts.__all__)


def test_every_name_in_all_resolves():
    for name in contracts.__all__:
        assert getattr(contracts, name, None) is not None, name


# ---------------------------------------------------------------------------
# 2. Enum members
# ---------------------------------------------------------------------------

EXPECTED_ENUMS = [
    (
        Category,
        [
            ("not_received", "not_received"),
            ("late", "late"),
            ("damaged", "damaged"),
            ("wrong_item", "wrong_item"),
            ("not_as_described", "not_as_described"),
            ("changed_mind", "changed_mind"),
            ("billing_error", "billing_error"),
            ("other", "other"),
        ],
    ),
    (
        Sentiment,
        [
            ("calm", "calm"),
            ("neutral", "neutral"),
            ("frustrated", "frustrated"),
            ("angry", "angry"),
            ("distressed", "distressed"),
        ],
    ),
    (
        Wants,
        [
            ("refund", "refund"),
            ("replacement", "replacement"),
            ("info", "info"),
            ("unknown", "unknown"),
        ],
    ),
    (
        Action,
        [
            ("refund_partial", "refund_partial"),
            ("refund_full", "refund_full"),
            ("replacement", "replacement"),
            ("handoff_to_merchant", "handoff_to_merchant"),
            ("dispute_provide_evidence", "dispute_provide_evidence"),
            ("dispute_accept_claim", "dispute_accept_claim"),
        ],
    ),
    (
        DisputeAction,
        [
            ("provide_evidence", "provide_evidence"),
            ("accept_claim", "accept_claim"),
            ("make_offer", "make_offer"),
        ],
    ),
]


@pytest.mark.parametrize("enum_cls,expected", EXPECTED_ENUMS, ids=lambda v: getattr(v, "__name__", "members"))
def test_enum_members_exact(enum_cls, expected):
    assert [(m.name, m.value) for m in enum_cls] == expected


@pytest.mark.parametrize("enum_cls,expected", EXPECTED_ENUMS, ids=lambda v: getattr(v, "__name__", "members"))
def test_enums_are_str_subclasses(enum_cls, expected):
    assert issubclass(enum_cls, str)


def test_enum_serialises_as_plain_string():
    assert json.dumps(Category.damaged) == '"damaged"'
    assert json.dumps(Action.refund_partial) == '"refund_partial"'


# ---------------------------------------------------------------------------
# 3. Exact dataclass fields
# ---------------------------------------------------------------------------

EXPECTED_FIELDS = [
    (Case, ("order_id", "capture_id", "customer_email", "category", "facts", "sentiment", "wants", "confidence", "raw_text")),
    (
        Rule,
        (
            "rule_id",
            "categories",
            "max_percent",
            "max_amount_minor",
            "min_order_value_minor",
            "max_order_value_minor",
            "max_order_age_days",
            "requires_photo",
            "action",
            "source_text",
        ),
    ),
    (Caps, ("per_refund_max_minor", "daily_total_max_minor", "max_order_age_days", "currency")),
    (Decision, ("action", "amount_minor", "currency", "rule_id", "reason", "needs_approval", "percent_applied")),
    (OrderSnapshot, ("order_id", "capture_id", "captured_amount_minor", "currency", "created_at", "refunded_amount_minor")),
    (RefundRecord, ("amount_minor", "created_at")),
    (History, ("refunds", "today_total_minor")),
    (OrderItem, ("name", "quantity", "unit_amount_minor")),
    (Capture, ("capture_id", "order_id", "status", "amount_minor", "currency", "refunded_amount_minor", "created_at")),
    (Order, ("order_id", "status", "amount_minor", "currency", "created_at", "payer_email", "captures", "items")),
    (Refund, ("refund_id", "capture_id", "status", "amount_minor", "currency", "created_at")),
    (
        Dispute,
        ("dispute_id", "status", "reason", "amount_minor", "currency", "created_at", "order_id", "capture_id", "evidence_due_by"),
    ),
    (DisputeActionResult, ("dispute_id", "action", "status", "raw")),
    (WebhookEvent, ("event_id", "event_type", "resource_type", "resource_id", "verified", "payload", "received_at")),
    (ProviderResult, ("value", "provider", "model", "rung")),
]


@pytest.mark.parametrize("cls,expected", EXPECTED_FIELDS, ids=[c.__name__ for c, _ in EXPECTED_FIELDS])
def test_dataclass_fields_exact(cls, expected):
    assert tuple(f.name for f in dataclasses.fields(cls)) == expected


@pytest.mark.parametrize("cls,expected", EXPECTED_FIELDS, ids=[c.__name__ for c, _ in EXPECTED_FIELDS])
def test_is_dataclass(cls, expected):
    assert dataclasses.is_dataclass(cls) is True


# ---------------------------------------------------------------------------
# 4. Frozen-ness
# ---------------------------------------------------------------------------


def test_every_sample_is_a_frozen_dataclass_instance():
    assert len(SAMPLES) == len(FROZEN_DATACLASSES)
    for cls, sample in zip(FROZEN_DATACLASSES, SAMPLES):
        assert type(sample) is cls


@pytest.mark.parametrize("sample", SAMPLES, ids=[type(s).__name__ for s in SAMPLES])
def test_frozen_dataclass_rejects_mutation(sample):
    first_field = dataclasses.fields(sample)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(sample, first_field, "mutated")


# ---------------------------------------------------------------------------
# 5. Money is int, never float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample", SAMPLES, ids=[type(s).__name__ for s in SAMPLES])
def test_money_fields_are_ints(sample):
    for field in dataclasses.fields(sample):
        if not field.name.endswith("_minor"):
            continue
        value = getattr(sample, field.name)
        # Optional policy bounds (e.g. Rule.min_order_value_minor) may legitimately
        # be None. A set bound must still be an int, never a float.
        if value is None:
            continue
        assert isinstance(value, int), (type(sample).__name__, field.name, type(value))
        assert not isinstance(value, bool), (type(sample).__name__, field.name)


def test_rule_optional_money_bounds_accept_none():
    rule = Rule(
        rule_id="r",
        categories=frozenset(),
        max_percent=None,
        max_amount_minor=None,
        min_order_value_minor=None,
        max_order_value_minor=None,
        max_order_age_days=None,
        requires_photo=False,
        action=Action.handoff_to_merchant,
        source_text="",
    )
    assert rule.max_amount_minor is None
    assert rule.min_order_value_minor is None


def test_caps_money_fields_are_plain_int():
    caps = Caps(per_refund_max_minor=5000, daily_total_max_minor=20000, max_order_age_days=90, currency="USD")
    assert type(caps.per_refund_max_minor) is int
    assert type(caps.daily_total_max_minor) is int


def test_dataclasses_do_not_coerce_float_money():
    # Documents that callers must pass ints: there is no float->int magic that
    # could hide a rounding bug.
    caps = Caps(per_refund_max_minor=100.5, daily_total_max_minor=1, max_order_age_days=1, currency="USD")
    assert isinstance(caps.per_refund_max_minor, float)


# ---------------------------------------------------------------------------
# 6. Runtime-checkable protocols
# ---------------------------------------------------------------------------


class _FullGateway:
    def get_order(self, order_id):
        return None

    def get_capture(self, capture_id):
        return None

    def refund_capture(self, capture_id, amount_minor, currency, idempotency_key):
        return None

    def list_disputes(self):
        return []

    def get_dispute(self, dispute_id):
        return None

    def provide_dispute_evidence(self, dispute_id, evidence, idempotency_key):
        return None

    def accept_dispute_claim(self, dispute_id, idempotency_key):
        return None

    def verify_webhook(self, headers, raw_body):
        return None


class _GatewayMissingVerifyWebhook:
    def get_order(self, order_id):
        return None

    def get_capture(self, capture_id):
        return None

    def refund_capture(self, capture_id, amount_minor, currency, idempotency_key):
        return None

    def list_disputes(self):
        return []

    def get_dispute(self, dispute_id):
        return None

    def provide_dispute_evidence(self, dispute_id, evidence, idempotency_key):
        return None

    def accept_dispute_claim(self, dispute_id, idempotency_key):
        return None


class _FullProvider:
    def classify(self, text, order):
        return None

    def compile_policy(self, text):
        return []

    def write_reply(self, case, decision):
        return ""


class _ProviderMissingWriteReply:
    def classify(self, text, order):
        return None

    def compile_policy(self, text):
        return []


class _FullModelProvider:
    @property
    def name(self):
        return "fake"

    def complete(self, system, user):
        return None


class _ModelProviderMissingComplete:
    @property
    def name(self):
        return "fake"


def test_paypal_gateway_is_runtime_checkable():
    assert isinstance(_FullGateway(), PayPalGateway) is True


def test_paypal_gateway_rejects_incomplete_implementation():
    assert isinstance(_GatewayMissingVerifyWebhook(), PayPalGateway) is False


def test_provider_is_runtime_checkable():
    assert isinstance(_FullProvider(), Provider) is True


def test_provider_rejects_incomplete_implementation():
    assert isinstance(_ProviderMissingWriteReply(), Provider) is False


def test_model_provider_is_runtime_checkable():
    assert isinstance(_FullModelProvider(), ModelProvider) is True


def test_model_provider_rejects_incomplete_implementation():
    assert isinstance(_ModelProviderMissingComplete(), ModelProvider) is False


@pytest.mark.parametrize("proto", [PayPalGateway, Provider, ModelProvider], ids=["PayPalGateway", "Provider", "ModelProvider"])
def test_protocol_flag(proto):
    assert getattr(proto, "_is_protocol", False) is True


# ---------------------------------------------------------------------------
# 7. ProviderResult is generic
# ---------------------------------------------------------------------------


def test_provider_result_constructs_with_str():
    result = ProviderResult[str](value="hi", provider="fake", model="m", rung=0)
    assert result.value == "hi"
    assert result.provider == "fake"
    assert result.model == "m"


def test_provider_result_rung_is_int():
    result = ProviderResult[str](value="hi", provider="fake", model="m", rung=2)
    assert isinstance(result.rung, int)
    assert type(result.rung) is int


def test_provider_result_is_generic_alias_of_itself():
    assert typing.get_origin(ProviderResult[str]) is ProviderResult
    assert typing.get_args(ProviderResult[str]) == (str,)
    assert ProviderResult[str] != ProviderResult[int]


# ---------------------------------------------------------------------------
# 8. Exception hierarchy
# ---------------------------------------------------------------------------


def test_settle_error_is_exception():
    assert issubclass(SettleError, Exception)


@pytest.mark.parametrize(
    "exc", [PayPalError, ProviderError, PolicyError, TokenError, NotFoundError], ids=lambda e: e.__name__
)
def test_direct_settle_subclasses(exc):
    assert issubclass(exc, SettleError)


def test_paypal_error_hierarchy():
    assert issubclass(PayPalTransientError, PayPalError)
    assert issubclass(GatewayTimeout, PayPalTransientError)
    assert issubclass(PayPalRejectedError, PayPalError)
    assert issubclass(GatewayTimeout, PayPalError)
    assert issubclass(GatewayTimeout, SettleError)


def test_provider_error_hierarchy():
    assert issubclass(ProviderTimeout, ProviderError)
    assert issubclass(ProviderInvalidOutput, ProviderError)
    assert issubclass(ProviderTimeout, SettleError)


_CATCHABLE = [
    (PayPalError, ("boom", 500, "body")),
    (PayPalTransientError, ("boom", 503, "body")),
    (GatewayTimeout, ("boom", 504, "body")),
    (PayPalRejectedError, ("boom", 422, "body")),
    (ProviderError, ("boom",)),
    (ProviderTimeout, ("boom",)),
    (ProviderInvalidOutput, ("boom",)),
    (PolicyError, ("boom",)),
    (TokenError, ("boom",)),
    (NotFoundError, ("boom",)),
]


@pytest.mark.parametrize("exc,args", _CATCHABLE, ids=[e.__name__ for e, _ in _CATCHABLE])
def test_all_errors_catchable_as_settle_error(exc, args):
    with pytest.raises(SettleError):
        raise exc(*args)


# ---------------------------------------------------------------------------
# 9. PayPalError constructs positionally
# ---------------------------------------------------------------------------


def test_paypal_error_three_positional_args():
    err = PayPalError("INVALID_REQUEST", 500, "body text")
    assert err.code == "INVALID_REQUEST"
    assert err.status == 500
    assert err.body == "body text"


def test_paypal_error_str_is_non_empty():
    err = PayPalError("INVALID_REQUEST", 500, "body text")
    assert isinstance(str(err), str)
    assert str(err)


def test_paypal_error_fourth_positional_message_overrides():
    err = PayPalError("X", 400, "b", "custom")
    assert err.args[0] == "custom"


def test_paypal_transient_error_constructs_positionally():
    err = PayPalTransientError("X", 503, "b")
    assert err.code == "X"
    assert err.status == 503
    assert err.body == "b"


# ---------------------------------------------------------------------------
# 10. get_type_hints resolves on the Provider protocol (guards the past bug)
# ---------------------------------------------------------------------------


def test_compile_policy_type_hints_resolve():
    hints = typing.get_type_hints(Provider.compile_policy)
    assert "return" in hints
    assert "Rule" in str(hints["return"])
    assert hints["text"] is str


def test_classify_type_hints_resolve():
    hints = typing.get_type_hints(Provider.classify)
    assert "return" in hints
    assert "Case" in str(hints["return"])


def test_write_reply_type_hints_resolve():
    hints = typing.get_type_hints(Provider.write_reply)
    assert "return" in hints
    assert hints["return"] is str


# ---------------------------------------------------------------------------
# 11. Whole-surface type hints resolve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", FROZEN_DATACLASSES, ids=[c.__name__ for c in FROZEN_DATACLASSES])
def test_dataclass_type_hints_resolve(cls):
    typing.get_type_hints(cls)


def test_rule_categories_hint_references_category():
    hints = typing.get_type_hints(Rule)
    assert "Category" in str(hints["categories"])


def test_case_facts_typed_dict_is_importable():
    # typing.is_typeddict is 3.10+; assert the 3.9-compatible shape instead.
    # case.py uses `from __future__ import annotations`, so raw annotations are
    # strings/ForwardRefs -- resolve them to prove the TypedDict is well-formed.
    assert CaseFacts is not None
    assert hasattr(CaseFacts, "__annotations__")
    hints = typing.get_type_hints(CaseFacts)
    assert "item_mentioned" in hints
    assert hints["item_mentioned"] is str
    assert hints["photo_provided"] is bool
    assert hints["quantity_affected"] is int
