"""Agent layer: the model judges, code decides money."""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .caps import SpendCapExceeded, StepCapExceeded
from .chain import FallbackChain
from .classify import ClassificationOutcome, classify_with_meta
from .fake import FakeProvider
from .keywords import classify_keywords
from .policy import (
    PolicyOutcome,
    compile_policy_with_meta,
    default_policy,
    rule_to_json,
)
from .provider import AgentProvider
from .reply import (
    reply_matches_decision,
    template_reply,
    write_reply,
)

__all__ = [
    "AgentProvider",
    "AnthropicProvider",
    "ClassificationOutcome",
    "FakeProvider",
    "FallbackChain",
    "PolicyOutcome",
    "SpendCapExceeded",
    "StepCapExceeded",
    "classify_keywords",
    "classify_with_meta",
    "compile_policy_with_meta",
    "default_policy",
    "reply_matches_decision",
    "rule_to_json",
    "template_reply",
    "write_reply",
]
