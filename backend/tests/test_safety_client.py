"""SafetyClient: both transports, retry, and the never-raise guarantee."""
from __future__ import annotations

import json
import math

import httpx
import pytest

from utils.safety.client import SafetyClient, _first_token_unsafe_prob

PROMPT = " <|begin_of_text|>...rendered..."


def _client(transport, handler, **kw):
    return SafetyClient(
        transport=transport,
        base_url="https://host.example",
        model="guard",
        api_key="k",
        transport_layer=httpx.MockTransport(handler),
        **kw,
    )


class TestOpenAICompletions:
    async def test_safe_verdict_and_request_shape(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"text": "\n\nsafe", "logprobs": None}]})

        v = await _client("openai_completions", handler).classify(PROMPT)
        assert v.status == "safe" and v.categories == []
        assert seen["url"] == "https://host.example/v1/completions"
        assert seen["auth"] == "Bearer k"
        assert seen["body"]["prompt"] == PROMPT
        assert seen["body"]["temperature"] == 0
        assert seen["body"]["logprobs"] == 1
        assert v.prompt_hash and v.model == "guard"

    async def test_unsafe_with_logprob(self):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "text": "\n\nunsafe\nS10",
                            "logprobs": {
                                "tokens": ["\n\n", "unsafe", "\n", "S", "10"],
                                "token_logprobs": [-0.1, -0.2, -0.3, -0.1, -0.1],
                                "top_logprobs": [{}, {"unsafe": -0.2}, {}, {}, {}],
                            },
                        }
                    ]
                },
            )

        v = await _client("openai_completions", handler).classify(PROMPT)
        assert v.status == "unsafe" and v.categories == ["S10"]
        # First token here is the leading newline, so no probability is claimed.
        assert v.unsafe_prob is None

    async def test_http_error_then_success_uses_retry(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(503, text="down")
            return httpx.Response(200, json={"choices": [{"text": "safe"}]})

        v = await _client("openai_completions", handler).classify(PROMPT)
        assert v.status == "safe" and calls["n"] == 2

    async def test_persistent_failure_is_unavailable_not_exception(self):
        def handler(request):
            raise httpx.ConnectError("refused")

        v = await _client("openai_completions", handler).classify(PROMPT)
        assert v.status == "unavailable"
        assert "ConnectError" in (v.error or "")

    async def test_malformed_output_is_unavailable(self):
        def handler(request):
            return httpx.Response(200, json={"choices": [{"text": "I cannot classify this."}]})

        v = await _client("openai_completions", handler).classify(PROMPT)
        assert v.status == "unavailable"
        assert v.raw == "I cannot classify this."
        assert "unparseable" in v.error

    async def test_bad_json_is_unavailable(self):
        def handler(request):
            return httpx.Response(200, text="<html>proxy error</html>")

        v = await _client("openai_completions", handler).classify(PROMPT)
        assert v.status == "unavailable"


class TestOllamaRaw:
    async def test_raw_generate_request_shape(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"response": "unsafe\nS1,S10", "done": True})

        v = await _client("ollama_raw", handler).classify(PROMPT)
        assert v.status == "unsafe" and v.categories == ["S1", "S10"]
        assert seen["url"] == "https://host.example/api/generate"
        assert seen["body"]["raw"] is True
        assert seen["body"]["stream"] is False
        assert seen["body"]["prompt"] == PROMPT
        assert seen["body"]["options"]["temperature"] == 0
        assert seen["body"]["options"]["num_ctx"] == 4096
        assert v.unsafe_prob is None


class TestConstruction:
    def test_unknown_transport_rejected(self):
        with pytest.raises(ValueError):
            SafetyClient(transport="grpc", base_url="x", model="y")

    def test_missing_base_url_rejected(self):
        with pytest.raises(ValueError):
            SafetyClient(transport="ollama_raw", base_url="", model="y")

    def test_from_config_env_fallback(self, monkeypatch):
        monkeypatch.setenv("SAFETY_BASE_URL", "https://env.example/")
        monkeypatch.setenv("SAFETY_MODEL", "llama-guard3:8b")
        monkeypatch.setenv("SAFETY_TRANSPORT", "ollama_raw")
        monkeypatch.setenv("SAFETY_API_KEY", "secret")
        c = SafetyClient.from_config({"enabled": True})
        assert c.base_url == "https://env.example"
        assert c.model == "llama-guard3:8b"
        assert c.transport == "ollama_raw"
        assert c.api_key == "secret"

    def test_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv("SAFETY_BASE_URL", "https://env.example/")
        c = SafetyClient.from_config(
            {"enabled": True, "base_url": "https://cfg.example", "model": "m", "transport": "openai_completions"}
        )
        assert c.base_url == "https://cfg.example"


class TestFirstTokenProb:
    def test_unsafe_first_token(self):
        lp = {"tokens": ["unsafe"], "token_logprobs": [math.log(0.9)], "top_logprobs": [{}]}
        assert _first_token_unsafe_prob(lp) == pytest.approx(0.9)

    def test_safe_first_token_with_unsafe_alternative(self):
        lp = {
            "tokens": ["safe"],
            "token_logprobs": [math.log(0.8)],
            "top_logprobs": [{"safe": math.log(0.8), "unsafe": math.log(0.2)}],
        }
        assert _first_token_unsafe_prob(lp) == pytest.approx(0.2)

    def test_missing(self):
        assert _first_token_unsafe_prob(None) is None
        assert _first_token_unsafe_prob({"tokens": [], "token_logprobs": []}) is None
