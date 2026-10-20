"""Anthropic provider over raw HTTP (no SDK).

UNVERIFIED against the live API — there is no key in this environment. The
request shape is asserted with a stub transport; nothing here has been run
against api.anthropic.com.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from contracts import (
    ProviderError,
    ProviderInvalidOutput,
    ProviderResult,
    ProviderTimeout,
)

__all__ = ["AnthropicProvider"]

_DEFAULT_BASE_URL = "https://api.anthropic.com"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    """A ``ModelProvider`` that speaks the Messages API directly."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-5-sonnet-latest",
        base_url: str = _DEFAULT_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = 30.0,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        kwargs: Dict[str, Any] = {"base_url": self._base_url, "timeout": timeout}
        if transport is not None:
            kwargs["transport"] = transport
        self._http = httpx.Client(**kwargs)

    @property
    def name(self) -> str:
        return "anthropic"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AnthropicProvider":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def complete(self, system: str, user: str) -> ProviderResult[str]:
        response = self._http.post(
            "/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": self._max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        status = response.status_code
        if status in (408, 504):
            raise ProviderTimeout("anthropic timeout (HTTP %d)" % (status,))
        if status == 429 or status >= 500:
            raise ProviderError("anthropic transient error (HTTP %d)" % (status,))
        if status >= 400:
            raise ProviderError(
                "anthropic rejected request (HTTP %d): %s"
                % (status, (response.text or "")[:200])
            )

        try:
            payload = response.json()
        except ValueError:
            raise ProviderInvalidOutput("anthropic response was not JSON")

        text = self._extract_text(payload)
        return ProviderResult(
            value=text, provider="anthropic", model=self._model, rung=0
        )

    @staticmethod
    def _extract_text(payload: Any) -> str:
        blocks = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(blocks, list):
            raise ProviderInvalidOutput("anthropic response has no content blocks")
        parts = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        if not parts:
            raise ProviderInvalidOutput("anthropic response had no text block")
        return "".join(parts)
