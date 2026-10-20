"""Integer minor-unit money conversion.

PayPal's JSON API speaks decimal strings ("12.34"). Settle never does. Every
amount inside the system is an ``int`` of minor units plus an ISO currency
string; conversion happens only at the HTTP boundary and is pure integer math.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

__all__ = ["to_minor", "from_minor", "parse_amount"]


def to_minor(value: Any) -> int:
    """Convert a PayPal decimal string to integer minor units.

    ``"12.34" -> 1234``, ``"12" -> 1200``, ``"0.05" -> 5``. Never uses float.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        raise ValueError("bool is not a money value")
    if isinstance(value, int):
        return value * 100
    text = str(value).strip()
    if not text:
        return 0
    negative = text.startswith("-")
    if text[0] in "+-":
        text = text[1:]
    if "." in text:
        whole, fraction = text.split(".", 1)
    else:
        whole, fraction = text, ""
    fraction = (fraction + "00")[:2]
    minor = int(whole or "0") * 100 + int(fraction or "0")
    return -minor if negative else minor


def from_minor(minor: int, currency: str = "") -> str:
    """Convert integer minor units to a PayPal decimal string.

    ``1234 -> "12.34"``. Exact for any magnitude; no float involved.
    """
    if not isinstance(minor, int) or isinstance(minor, bool):
        raise TypeError("minor units must be an int, got %r" % (type(minor).__name__,))
    sign = "-" if minor < 0 else ""
    magnitude = -minor if minor < 0 else minor
    return "%s%d.%02d" % (sign, magnitude // 100, magnitude % 100)


def parse_amount(amount: Mapping[str, Any]) -> Tuple[int, str]:
    """Pull ``(minor_units, currency)`` out of a PayPal ``amount`` object."""
    if not amount:
        return 0, ""
    return to_minor(amount.get("value")), str(amount.get("currency_code", ""))
