"""PayPal access for Settle.

``FakePayPalGateway`` is the verifiable implementation (no credentials needed).
``PayPalClient`` is the real REST client; it is UNVERIFIED against live PayPal
until sandbox credentials exist.
"""

from __future__ import annotations

from .client import PayPalClient
from .fake import FakePayPalGateway
from .money import from_minor, parse_amount, to_minor

__all__ = [
    "FakePayPalGateway",
    "PayPalClient",
    "to_minor",
    "from_minor",
    "parse_amount",
]
