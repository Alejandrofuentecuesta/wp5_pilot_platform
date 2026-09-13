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

TRANSPORTS = ("openai_completions", "ollama_raw")


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


class SafetyClient:
    def __init__(
        self,
        *,
        transport: str,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout_s: float = 8.0,
        max_tokens: int = 20,
        num_ctx: int = 4096,
        transport_layer: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        if transport not in TRANSPORTS:
            raise ValueError(f"unknown safety transport {transport!r}; expected one of {TRANSPORTS}")
        if not base_url or not model:
            raise ValueError("safety client needs base_url and model")
        self.transport = transport
        self.base_url = base_url.rstrip("/")
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
        return cls(
            transport=cfg.get("transport") or os.getenv("SAFETY_TRANSPORT", "openai_completions"),
            base_url=cfg.get("base_url") or os.getenv("SAFETY_BASE_URL", ""),
            model=cfg.get("model") or os.getenv("SAFETY_MODEL", ""),
            timeout_s=float(cfg.get("timeout_s", 8.0)),
            num_ctx=int(cfg.get("num_ctx", 4096)),
        )

    # ── public ────────────────────────────────────────────────────────────

    async def classify(self, prompt: str) -> SafetyVerdict:
        """Classify one rendered prompt. One retry on transport error."""
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        t0 = time.monotonic()
        last_error: Optional[str] = None
        for attempt in (1, 2):
            try:
                raw, unsafe_prob = await self._request(prompt)
            except Exception as exc:  # transport, timeout, HTTP status, bad JSON
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            status, categories = parse_verdict(raw)
            return SafetyVerdict(
                status=status,
                categories=categories,
                raw=raw,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                unsafe_prob=unsafe_prob,
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
