"""Anthropic provider request shape and error mapping (stub transport).

UNVERIFIED against the live API. These tests assert what the client sends, not
what Anthropic returns.
"""

from __future__ import annotations

import json
from typing import Any, List

import httpx
import pytest

from backend.agent.anthropic import AnthropicProvider
from contracts import ProviderError, ProviderInvalidOutput, ProviderTimeout


class Recorder:
    def __init__(self, responder):
        self.requests: List[httpx.Request] = []
        self._responder = responder

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def last(self) -> httpx.Request:
        assert self.requests
        return self.requests[-1]


def make_provider(recorder: Recorder) -> AnthropicProvider:
    return AnthropicProvider(
        "key-123",
        model="claude-test",
        transport=httpx.MockTransport(recorder),
    )


def test_request_shape():
    recorder = Recorder(
        lambda request: httpx.Response(
            200, json={"content": [{"type": "text", "text": "hello"}]}
        )
    )
    provider = make_provider(recorder)
    result = provider.complete("SYSTEM", "USER")

    assert result.value == "hello"
    assert result.provider == "anthropic"
    assert result.model == "claude-test"

    call = recorder.last()
    assert call.method == "POST"
    assert call.url.path == "/v1/messages"
    assert call.headers["x-api-key"] == "key-123"
    assert call.headers["anthropic-version"] == "2023-06-01"

    body = json.loads(call.content.decode("utf-8"))
    assert body["model"] == "claude-test"
    assert body["system"] == "SYSTEM"
    assert body["messages"] == [{"role": "user", "content": "USER"}]
    assert body["max_tokens"] == 1024


def test_concatenates_multiple_text_blocks():
    recorder = Recorder(
        lambda request: httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "a"},
                    {"type": "tool_use", "id": "x"},
                    {"type": "text", "text": "b"},
                ]
            },
        )
    )
    provider = make_provider(recorder)
    assert provider.complete("S", "U").value == "ab"


def test_500_raises_provider_error():
    recorder = Recorder(lambda request: httpx.Response(500, json={}))
    provider = make_provider(recorder)
    with pytest.raises(ProviderError):
        provider.complete("S", "U")


def test_429_raises_provider_error():
    recorder = Recorder(lambda request: httpx.Response(429, json={}))
    provider = make_provider(recorder)
    with pytest.raises(ProviderError):
        provider.complete("S", "U")


def test_504_raises_provider_timeout():
    recorder = Recorder(lambda request: httpx.Response(504, json={}))
    provider = make_provider(recorder)
    with pytest.raises(ProviderTimeout):
        provider.complete("S", "U")


def test_400_raises_provider_error():
    recorder = Recorder(lambda request: httpx.Response(400, json={}))
    provider = make_provider(recorder)
    with pytest.raises(ProviderError):
        provider.complete("S", "U")


def test_invalid_json_raises_invalid_output():
    recorder = Recorder(lambda request: httpx.Response(200, content=b"not json"))
    provider = make_provider(recorder)
    with pytest.raises(ProviderInvalidOutput):
        provider.complete("S", "U")


def test_missing_text_block_raises_invalid_output():
    recorder = Recorder(
        lambda request: httpx.Response(200, json={"content": [{"type": "tool_use"}]})
    )
    provider = make_provider(recorder)
    with pytest.raises(ProviderInvalidOutput):
        provider.complete("S", "U")


def test_provider_name():
    recorder = Recorder(lambda request: httpx.Response(200, json={}))
    provider = make_provider(recorder)
    assert provider.name == "anthropic"
