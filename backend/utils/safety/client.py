"""Transport client for the safety classifier.

Sends the policy (system message) and the conversation excerpt (user message)
to the classifier and returns a ``SafetyVerdict``. The client never raises:
every failure becomes a verdict with ``status="unavailable"`` and ``error``
set, and the caller decides what to do with that (the screen withholds the
turn).

Transports
----------
``openai_chat``
    OpenAI-compatible ``POST {base_url}/v1/chat/completions``: Konstanz's vLLM
    serving gpt-oss-safeguard in production, or Ollama for local tests. Sends
    ``reasoning_effort`` and keeps the model's reasoning, which vLLM returns
    as ``reasoning_content`` and Ollama as ``reasoning``.
``anthropic_messages``
    Anthropic's ``POST {base_url}/v1/messages`` (default host:
    ``https://api.anthropic.com``), for Claude as an alternative classifier.
    It receives the same policy and excerpt.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import httpx

from utils.safety.prompt import parse_verdict

TRANSPORTS = ("openai_chat", "anthropic_messages")
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
KONSTANZ_DEFAULT_BASE_URL = "https://whatif.inf.uni-konstanz.de/v1"
SAFEGUARD_DEFAULT_MODEL = "openai/gpt-oss-safeguard-20b"
DEFAULT_TIMEOUT_S = 20.0
# The model reasons before it answers; the answer itself is one short JSON
# object. The cap covers both.
DEFAULT_MAX_TOKENS = 2000
REASONING_EFFORT = "medium"


@dataclass
class SafetyVerdict:
    status: str  # "safe" | "unsafe" | "unavailable" | "unscreened"
    categories: List[str] = field(default_factory=list)
    raw: str = ""
    model: str = ""
    latency_ms: int = 0
    error: Optional[str] = None
    prompt_hash: str = ""
    rationale: Optional[str] = None
    # The model's reasoning before its answer, when the host returns it.
    reasoning: Optional[str] = None
    # Set by the screen: which policy text produced this verdict.
    policy_version: Optional[str] = None


class SafetyClient:
    def __init__(
        self,
        *,
        transport: str,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport_layer: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if transport not in TRANSPORTS:
            raise ValueError(f"unknown safety transport {transport!r}; expected one of {TRANSPORTS}")
        if not model:
            raise ValueError("safety client needs a model")
        base = (base_url or "").rstrip("/")
        if transport == "anthropic_messages":
            base = base or ANTHROPIC_DEFAULT_BASE_URL
        elif not base:
            raise ValueError("safety client needs a base_url")
        # Konstanz is configured with a /v1 base elsewhere in the platform;
        # the endpoints below add /v1 themselves.
        if base.endswith("/v1"):
            base = base[:-3]
        self.transport = transport
        self.base_url = base
        self.model = model
        # Environment fallbacks live in from_config only, per transport.
        self.api_key = api_key or ""
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        # httpx transport override, used by tests to fake the host.
        self._transport_layer = transport_layer

    @classmethod
    def from_config(cls, cfg: dict) -> "SafetyClient":
        """Build from ``experimental.safety`` with environment fallbacks."""
        transport = cfg.get("transport") or os.getenv("SAFETY_TRANSPORT", "openai_chat")
        if transport == "anthropic_messages":
            # Never fall back to the Konstanz URL or key: that would send the
            # Konstanz credential to Anthropic.
            base_url = os.getenv("ANTHROPIC_BASE_URL", "")
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            model = cfg.get("model") or ""
        else:
            base_url = (
                cfg.get("base_url")
                or os.getenv("SAFETY_BASE_URL", "")
                or os.getenv("KONSTANZ_BASE_URL", KONSTANZ_DEFAULT_BASE_URL)
            )
            api_key = os.getenv("SAFETY_API_KEY", "") or os.getenv("KONSTANZ_API_KEY", "")
            model = cfg.get("model") or os.getenv("SAFETY_MODEL", "") or SAFEGUARD_DEFAULT_MODEL
        return cls(
            transport=transport,
            base_url=base_url,
            model=model,
            api_key=api_key or None,
            timeout_s=float(cfg.get("timeout_s", DEFAULT_TIMEOUT_S)),
        )

    # ── public ────────────────────────────────────────────────────────────

    async def classify(self, policy: str, excerpt: str) -> SafetyVerdict:
        """Classify one excerpt against the policy. One retry on transport error."""
        prompt_hash = hashlib.sha256(f"{policy}\n\n{excerpt}".encode("utf-8")).hexdigest()
        t0 = time.monotonic()
        last_error: Optional[str] = None
        for _attempt in (1, 2):
            try:
                if self.transport == "anthropic_messages":
                    raw, reasoning = await self._anthropic_messages(policy, excerpt)
                else:
                    raw, reasoning = await self._openai_chat(policy, excerpt)
            except Exception as exc:  # transport, timeout, HTTP status, bad JSON
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            status, categories, rationale = parse_verdict(raw)
            return SafetyVerdict(
                status=status,
                categories=categories,
                raw=raw,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                rationale=rationale,
                reasoning=reasoning,
                error=None if status != "unavailable" else f"unparseable output: {raw[:200]!r}",
                prompt_hash=prompt_hash,
            )
        return SafetyVerdict(
            status="unavailable",
            model=self.model,
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=last_error,
            prompt_hash=prompt_hash,
        )

    # ── transports ────────────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport_layer)

    async def _openai_chat(self, policy: str, excerpt: str) -> Tuple[str, Optional[str]]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": policy},
                {"role": "user", "content": excerpt},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "reasoning_effort": REASONING_EFFORT,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with self._http() as client:
            resp = await client.post(f"{self.base_url}/v1/chat/completions", json=body, headers=headers)
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
        reasoning = message.get("reasoning_content") or message.get("reasoning") or None
        return (message.get("content") or "").strip(), reasoning

    async def _anthropic_messages(self, policy: str, excerpt: str) -> Tuple[str, Optional[str]]:
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": policy,
            "messages": [{"role": "user", "content": excerpt}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        async with self._http() as client:
            resp = await client.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
        resp.raise_for_status()
        parts = [
            block.get("text", "")
            for block in resp.json().get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts).strip(), None
