from __future__ import annotations


class SettleError(Exception):
    """Base exception for all settlement errors."""
    pass


class PayPalError(SettleError):
    """PayPal API error with response details."""

    def __init__(self, code: str, status: int, body: str, message: str = "") -> None:
        super().__init__(message or f"PayPal error {code} (HTTP {status})")
        self.code = code
        self.status = status
        self.body = body


class PayPalTransientError(PayPalError):
    """Transient PayPal error that may succeed on retry."""
    pass


class GatewayTimeout(PayPalTransientError):
    """PayPal gateway timeout error."""
    pass


class PayPalRejectedError(PayPalError):
    """PayPal rejected the request (non-transient)."""
    pass


class ProviderError(SettleError):
    """Provider (LLM) error."""
    pass


class ProviderTimeout(ProviderError):
    """Provider request timed out."""
    pass


class ProviderInvalidOutput(ProviderError):
    """Provider returned invalid/unparseable output."""
    pass


class PolicyError(SettleError):
    """Policy compilation or evaluation error."""
    pass


class TokenError(SettleError):
    """Authentication/token error."""
    pass


class NotFoundError(SettleError):
    """Resource not found error."""
    pass