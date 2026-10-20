"""``contracts.Provider`` implementation wired to a provider chain."""

from __future__ import annotations

from typing import List

from contracts import Case, Decision, Order, Rule

from .chain import FallbackChain
from .classify import classify_with_meta
from .policy import compile_policy_with_meta
from .reply import write_reply

__all__ = ["AgentProvider"]


class AgentProvider:
    """Satisfies the frozen ``Provider`` protocol using a model chain."""

    def __init__(self, chain: FallbackChain) -> None:
        self._chain = chain

    def classify(self, text: str, order: Order) -> Case:
        return classify_with_meta(text, order, self._chain).case

    def compile_policy(self, text: str) -> List[Rule]:
        return compile_policy_with_meta(text, self._chain).rules

    def write_reply(self, case: Case, decision: Decision) -> str:
        return write_reply(case, decision, self._chain)
