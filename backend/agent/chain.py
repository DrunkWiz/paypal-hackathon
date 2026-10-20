"""Provider fallback chain.

Falls through on **provider failure only**. A spend cap or a step cap is not a
provider failure and must propagate: retrying a cheaper-sounding next rung after
a budget stop would be exactly the wrong behaviour.
"""

from __future__ import annotations

from typing import List, Sequence

from contracts import ProviderError, ProviderResult

from .caps import SpendCapExceeded, StepCapExceeded

__all__ = ["FallbackChain"]


class FallbackChain:
    """Try providers in order, recording which rung answered."""

    def __init__(self, providers: Sequence[object]) -> None:
        self._providers: List[object] = list(providers)

    @property
    def size(self) -> int:
        return len(self._providers)

    def complete(self, system: str, user: str) -> ProviderResult[str]:
        last_error: Exception = ProviderError("no providers configured")
        for index, provider in enumerate(self._providers):
            try:
                result = provider.complete(system, user)  # type: ignore[attr-defined]
            except (SpendCapExceeded, StepCapExceeded):
                # Budget and step caps are not provider failures.
                raise
            except ProviderError as exc:
                last_error = exc
                continue
            return ProviderResult(
                value=result.value,
                provider=result.provider,
                model=result.model,
                rung=index,
            )
        raise ProviderError("all providers failed: %s" % (last_error,)) from last_error
