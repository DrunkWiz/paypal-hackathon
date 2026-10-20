from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Mapping, Protocol, TypeVar
from typing import runtime_checkable

from .case import Case
from .paypal import Order
from .policy import Decision, Rule


T = TypeVar("T")


@runtime_checkable
class Provider(Protocol):
    def classify(self, text: str, order: Order) -> Case: ...
    def compile_policy(self, text: str) -> List[Rule]: ...
    def write_reply(self, case: Case, decision: Decision) -> str: ...


@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    value: T
    provider: str
    model: str
    rung: int


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...
    def complete(self, system: str, user: str) -> ProviderResult[str]: ...