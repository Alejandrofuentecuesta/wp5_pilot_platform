"""SafetyClient: both transports, retry, and the never-raise guarantee."""
from __future__ import annotations

import json

import httpx
import pytest

from utils.safety.client import (
    ANTHROPIC_DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_S,
    SAFEGUARD_DEFAULT_MODEL,
    SafetyClient,
)

POLICY = "# Policy\n..."
EXCERPT = "User: hola\n\nAgent 1: adiós\n\n[Assess the last message above, written by Agent 1. ...]"
UNSAFE = '{"violation": 1, "categories": ["S10"], "rationale": "Dehumanises a group."}'
SAFE = '{"violation": 0, "categories": [], "rationale": "Political insult only."}'


def _client(transport, handler, base_url="https://host.example/v1", **kw):
    return SafetyClient(
        transport=transport,
        base_url=base_url,
        model="safeguard",
        api_key="k",
        transport_layer=httpx.MockTransport(handler),
        **kw,
    )


def _chat(content, **message):
    return httpx.Response(200, json={"choices": [{"message": {"content": content, **message}}]})


class TestOpenAIChat:
    async def test_request_shape_and_safe_verdict(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return _chat(SAFE)

        v = await _client("openai_chat", handler).classify(POLICY, EXCERPT)
        assert v.status == "safe" and v.categories == [] and v.rationale == "Political insult only."
        assert seen["url"] == "https://host.example/v1/chat/completions"
        assert seen["auth"] == "Bearer k"
        body = seen["body"]
        assert body["messages"] == [
            {"role": "system", "content": POLICY},
            {"role": "user", "content": EXCERPT},
        ]
        assert body["temperature"] == 0
        assert body["reasoning_effort"] == "medium"
        assert body["model"] == "safeguard"
        assert v.prompt_hash and v.model == "safeguard"

    async def test_unsafe_keeps_vllm_reasoning(self):
        v = await _client("openai_chat", lambda r: _chat(UNSAFE, reasoning_content="The message calls ...")).classify(
            POLICY, EXCERPT
        )
        assert v.status == "unsafe" and v.categories == ["S10"]
        assert v.reasoning == "The message calls ..."
        assert v.raw == UNSAFE

    async def test_keeps_ollama_reasoning(self):
        v = await _client("openai_chat", lambda r: _chat(SAFE, reasoning="Ollama thinking")).classify(POLICY, EXCERPT)
        assert v.reasoning == "Ollama thinking"

    async def test_base_url_without_v1_is_accepted(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return _chat(SAFE)

        await _client("openai_chat", handler, base_url="https://host.example/").classify(POLICY, EXCERPT)
        assert seen["url"] == "https://host.example/v1/chat/completions"

    async def test_http_error_then_success_uses_retry(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="down")
            return _chat(SAFE)

        v = await _client("openai_chat", handler).classify(POLICY, EXCERPT)
        assert v.status == "safe" and calls["n"] == 2

    async def test_persistent_failure_is_unavailable_not_exception(self):
        def handler(request):
            raise httpx.ConnectError("refused")

        v = await _client("openai_chat", handler).classify(POLICY, EXCERPT)
        assert v.status == "unavailable"
        assert "ConnectError" in v.error

    async def test_empty_content_is_unavailable(self):
        # e.g. the reasoning used up the token budget before the answer.
        v = await _client("openai_chat", lambda r: _chat(None, reasoning_content="long...")).classify(POLICY, EXCERPT)
        assert v.status == "unavailable"
        assert "unparseable" in v.error

    async def test_bad_response_body_is_unavailable(self):
        v = await _client("openai_chat", lambda r: httpx.Response(200, text="not json")).classify(POLICY, EXCERPT)
        assert v.status == "unavailable"


class TestAnthropicMessages:
    async def test_request_shape_and_verdict(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("x-api-key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"content": [{"type": "text", "text": UNSAFE}]})

        v = await _client("anthropic_messages", handler, base_url="").classify(POLICY, EXCERPT)
        assert v.status == "unsafe" and v.categories == ["S10"]
        assert seen["url"] == f"{ANTHROPIC_DEFAULT_BASE_URL}/v1/messages"
        assert seen["key"] == "k"
        assert seen["body"]["system"] == POLICY
        assert seen["body"]["messages"] == [{"role": "user", "content": EXCERPT}]
        assert seen["body"]["temperature"] == 0


class TestConstruction:
    def test_unknown_transport_rejected(self):
        with pytest.raises(ValueError):
            SafetyClient(transport="openai_completions", base_url="https://h", model="m")

    def test_missing_base_url_rejected(self):
        with pytest.raises(ValueError):
            SafetyClient(transport="openai_chat", base_url="", model="m")

    def test_missing_model_rejected(self):
        with pytest.raises(ValueError):
            SafetyClient(transport="openai_chat", base_url="https://h", model="")

    def test_defaults_reuse_konstanz(self, monkeypatch):
        for var in ("SAFETY_TRANSPORT", "SAFETY_BASE_URL", "SAFETY_MODEL", "SAFETY_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("KONSTANZ_BASE_URL", "https://konstanz.example/v1")
        monkeypatch.setenv("KONSTANZ_API_KEY", "konstanz-key")
        c = SafetyClient.from_config({"enabled": True})
        assert c.transport == "openai_chat"
        assert c.base_url == "https://konstanz.example"
        assert c.model == SAFEGUARD_DEFAULT_MODEL
        assert c.api_key == "konstanz-key"
        assert c.timeout_s == DEFAULT_TIMEOUT_S

    def test_safety_overrides_take_priority_over_konstanz(self, monkeypatch):
        monkeypatch.setenv("KONSTANZ_BASE_URL", "https://konstanz.example/v1")
        monkeypatch.setenv("KONSTANZ_API_KEY", "konstanz-key")
        monkeypatch.setenv("SAFETY_BASE_URL", "http://localhost:11434")
        monkeypatch.setenv("SAFETY_MODEL", "gpt-oss-safeguard:20b")
        monkeypatch.setenv("SAFETY_API_KEY", "safety-key")
        c = SafetyClient.from_config({"enabled": True})
        assert c.base_url == "http://localhost:11434"
        assert c.model == "gpt-oss-safeguard:20b"
        assert c.api_key == "safety-key"

    def test_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SAFETY_BASE_URL", "https://env.example")
        c = SafetyClient.from_config({"base_url": "https://cfg.example/v1", "model": "m", "timeout_s": 5})
        assert c.base_url == "https://cfg.example" and c.model == "m" and c.timeout_s == 5

    def test_anthropic_never_reuses_konstanz_host_or_key(self, monkeypatch):
        monkeypatch.setenv("SAFETY_BASE_URL", "https://konstanz.example/v1")
        monkeypatch.setenv("SAFETY_API_KEY", "konstanz-key")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        c = SafetyClient.from_config({"transport": "anthropic_messages", "model": "claude-haiku-4-5-20251001"})
        assert c.base_url == ANTHROPIC_DEFAULT_BASE_URL
        assert c.api_key == ""
