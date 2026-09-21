"""Transport client for the safety model.

Sends a pre-rendered Llama Guard prompt to one of two hosts and returns a
``SafetyVerdict``. The client never raises: every failure becomes a verdict
with ``status="unavailable"`` and ``error`` set, and the caller decides what
to do with that (the screen withholds the turn).

Transports
----------
``openai_completions``
    vLLM's OpenAI-compatible ``POST {base_url}/v1/completions`` with the raw
    prompt. Requests one logprob per token so the unsafe probability of the
    first token can be recorded alongside the verdict.
``ollama_raw``
    Ollama's native ``POST {base_url}/api/generate`` with ``raw: true`` so
    Ollama's own template is bypassed and the prompt is used verbatim.
    ``base_url`` is the Ollama root: ``http://host:11434`` for a direct
    host, or ``https://<open-webui>/ollama`` through Open WebUI's proxy.
``anthropic_messages``
    Anthropic's ``POST {base_url}/v1/messages`` (default host:
    ``https://api.anthropic.com``). Used for a chat-completions classifier
    (e.g. Claude Haiku) instead of a self-hosted Llama Guard. Takes a
    system/user pair (see ``classify_chat`` and
    ``utils.safety.prompt.render_chat_prompt``) rather than one raw prompt.
"""
from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from utils.safety.prompt import parse_verdict

TRANSPORTS = ("openai_completions", "ollama_raw", "anthropic_messages")
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class SafetyVerdict:
    status: str  # "safe" | "unsafe" | "unavailable"
    categories: List[str] = field(default_factory=list)
    raw: str = ""
    model: str = ""
    latency_ms: int = 0
    unsafe_prob: Optional[float] = None
    error: Optional[str] = None
    prompt_hash: str = ""
    # One-sentence explanation, when the classifier provides one. Llama
    # Guard's own template never asks for this; a chat-completions
    # classifier (see ``SafetyClient.classify_chat``) always does.
    rationale: Optional[str] = None


class SafetyClient:
    def __init__(
        self,
        *,
        transport: str,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_s: float = 8.0,
        # 20 used to be enough for Llama Guard's own two-line output. A chat
        # classifier (anthropic_messages) is also asked for a one-sentence
        # rationale, which needs more room. Harmless either way: Llama Guard
        # stops at its own EOS right after the two lines regardless of the cap.
        max_tokens: int = 80,
        num_ctx: int = 4096,
        transport_layer: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if transport not in TRANSPORTS:
            raise ValueError(f"unknown safety transport {transport!r}; expected one of {TRANSPORTS}")
        if not model:
            raise ValueError("safety client needs a model")
        if not base_url and transport != "anthropic_messages":
            raise ValueError("safety client needs base_url and model")
        self.transport = transport
        self.base_url = (base_url or (ANTHROPIC_DEFAULT_BASE_URL if transport == "anthropic_messages" else "")).rstrip("/")
        self.model = model
        self.api_key = api_key if api_key is not None else os.getenv("SAFETY_API_KEY", "")
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        # Ollama only: context window to load the model with. Llama Guard
        # prompts are short, and the server default (often 32k) would reserve
        # far more GPU memory than needed.
        self.num_ctx = num_ctx
        # httpx transport override, used by tests to fake the host.
        self._transport_layer = transport_layer

    @classmethod
    def from_config(cls, cfg: dict) -> "SafetyClient":
        """Build from ``experimental.safety`` with environment fallbacks."""
        transport = cfg.get("transport") or os.getenv("SAFETY_TRANSPORT", "openai_completions")
        if transport == "anthropic_messages":
            # SAFETY_BASE_URL/API_KEY normally identify the self-hosted Llama
            # Guard service. Reusing them for Claude routes /v1/messages to
            # the vLLM host and can also leak the wrong credential. Anthropic
            # therefore has provider-specific fallbacks and otherwise uses
            # the official API host filled in by __init__.
            base_url = os.getenv("ANTHROPIC_BASE_URL", "")
            api_key = os.getenv("ANTHROPIC_API_KEY", "") or os.getenv("SAFETY_API_KEY", "")
        else:
            base_url = cfg.get("base_url") or os.getenv("SAFETY_BASE_URL", "")
            api_key = os.getenv("SAFETY_API_KEY", "")
        return cls(
            transport=transport,
            base_url=base_url,
            model=cfg.get("model") or os.getenv("SAFETY_MODEL", ""),
            api_key=api_key or None,
            timeout_s=float(cfg.get("timeout_s", 8.0)),
            num_ctx=int(cfg.get("num_ctx", 4096)),
        )

    # ── public ────────────────────────────────────────────────────────────

    async def classify(self, prompt: str) -> SafetyVerdict:
        """Classify one rendered raw prompt (Llama Guard transports). One retry on transport error."""
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        t0 = time.monotonic()
        last_error: Optional[str] = None
        for attempt in (1, 2):
            try:
                raw, unsafe_prob = await self._request(prompt)
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
                unsafe_prob=unsafe_prob,
                rationale=rationale,
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

    async def classify_chat(self, system: str, user: str) -> SafetyVerdict:
        """Classify a System/User prompt pair (the ``anthropic_messages`` transport).

        Parallel to ``classify()`` for classifiers that take a chat-style
        system/user pair (see ``utils.safety.prompt.render_chat_prompt``)
        instead of one raw completion prompt. Same never-raise, one-retry
        behaviour.
        """
        prompt_hash = hashlib.sha256(f"{system}\n\n{user}".encode("utf-8")).hexdigest()
        t0 = time.monotonic()
        last_error: Optional[str] = None
        for attempt in (1, 2):
            try:
                raw = await self._anthropic_messages(system, user)
            except Exception as exc:
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

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport_layer)

    async def _request(self, prompt: str):
        if self.transport == "openai_completions":
            return await self._openai_completions(prompt)
        return await self._ollama_raw(prompt)

    async def _openai_completions(self, prompt: str):
        body = {
            "model": self.model,
            "prompt": prompt,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "logprobs": 1,
        }
        async with self._http() as client:
            resp = await client.post(f"{self.base_url}/v1/completions", json=body, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        text = choice.get("text") or ""
        unsafe_prob = _first_token_unsafe_prob(choice.get("logprobs"))
        return text, unsafe_prob

    async def _ollama_raw(self, prompt: str):
        body = {
            "model": self.model,
            "prompt": prompt,
            "raw": True,
            "stream": False,
            "options": {"temperature": 0, "num_predict": self.max_tokens, "num_ctx": self.num_ctx},
        }
        async with self._http() as client:
            resp = await client.post(
                f"{self.base_url}/api/generate", json=body, headers=self._headers()
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response") or "", None

    async def _anthropic_messages(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        async with self._http() as client:
            resp = await client.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        parts = [
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts).strip()


def _first_token_unsafe_prob(logprobs: Optional[dict]) -> Optional[float]:
    """Probability of the first generated token being 'unsafe', when available.

    vLLM returns ``top_logprobs`` as a list of ``{token: logprob}`` per
    position. The model card defines the unsafe score as the probability of
    the first token; if the first token is 'unsafe' its own probability is
    used, if it is 'safe' the complement is reported when 'unsafe' appears
    among the alternatives, otherwise ``None``.
    """
    if not logprobs:
        return None
    tops = logprobs.get("top_logprobs") or []
    tokens = logprobs.get("tokens") or []
    token_lps = logprobs.get("token_logprobs") or []
    if not tokens or not token_lps or token_lps[0] is None:
        return None
    first = tokens[0].strip().lower()
    first_p = math.exp(token_lps[0])
    if first == "unsafe":
        return first_p
    if first == "safe":
        alts = tops[0] if tops else {}
        for tok, lp in (alts or {}).items():
            if tok.strip().lower() == "unsafe" and lp is not None:
                return math.exp(lp)
        return None
    return None
