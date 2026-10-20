"""Budget and step-cap errors.

These are deliberately **not** ``ProviderError`` subclasses. The fallback chain
falls through on provider failure only; a spend cap or a step cap must stop the
whole operation rather than quietly trying a cheaper-sounding next rung.
"""

from __future__ import annotations

from contracts import SettleError

__all__ = ["SpendCapExceeded", "StepCapExceeded"]


class SpendCapExceeded(SettleError):
    """The configured spend budget for this operation is exhausted."""


class StepCapExceeded(SettleError):
    """The configured maximum number of model steps is exhausted."""
