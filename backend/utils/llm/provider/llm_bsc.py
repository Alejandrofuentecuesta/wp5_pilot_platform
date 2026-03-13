import asyncio
import os
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

load_dotenv()

DEFAULT_BASE_URL = "http://212.128.226.126/incivility/api/v1"


def _get_field(obj: Any, field: str) -> Any:
    """Read a value from either an SDK object or a plain dict."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(field)
    value = getattr(obj, field, None)
    if value is not None:
        return value
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, dict):
        return extra.get(field)
    return None


def _coerce_text(value: Any) -> Optional[str]:
    """Flatten text fields returned by OpenAI-compatible SDKs."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None

    if not isinstance(value, list):
        return None

    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                parts.append(stripped)
            continue

        text = _get_field(item, "text") or _get_field(item, "content")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    if not parts:
        return None
    return "\n".join(parts)


def _extract_message_text(completion: Any) -> Optional[str]:
    """Extract assistant text, falling back to `reasoning_content` for BSC."""
    choices = _get_field(completion, "choices")
    if not choices:
        return None

    message = _get_field(choices[0], "message")
    if message is None:
        return None

    return (
        _coerce_text(_get_field(message, "content"))
        or _coerce_text(_get_field(message, "reasoning_content"))
    )


class BSCClient:
    """Client for the BSC WHAT-IF incivility endpoint (OpenAI-compatible)."""

    def __init__(
        self,
        model_name: str = "incivility",
        temperature: float = None,
        top_p: float = None,
        max_tokens: int = 1024,
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.base_url = os.getenv("BSC_API_BASE_URL", DEFAULT_BASE_URL)
        api_key = os.getenv("BSC_API_KEY", "")

        self.client = OpenAI(base_url=self.base_url, api_key=api_key)

        try:
            self.aclient = AsyncOpenAI(base_url=self.base_url, api_key=api_key)
        except Exception:
            self.aclient = None

    def _build_kwargs(self, prompt: str, system_prompt: str = None) -> dict:
        messages = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p
        return kwargs

    def generate_response(
        self,
        prompt: str,
        max_retries: int = 1,
        system_prompt: str = None,
    ) -> Optional[str]:
        attempts = 0
        last_error = None

        while attempts <= max_retries:
            try:
                completion = self.client.chat.completions.create(
                    **self._build_kwargs(prompt, system_prompt=system_prompt)
                )
                return _extract_message_text(completion)
            except Exception as e:
                last_error = str(e)
                attempts += 1
                if attempts > max_retries:
                    print(f"LLM call failed after {max_retries + 1} attempts: {last_error}")
                    return None

        return None

    async def generate_response_async(
        self,
        prompt: str,
        max_retries: int = 1,
        system_prompt: str = None,
    ) -> Optional[str]:
        attempts = 0
        last_error = None

        while attempts <= max_retries:
            try:
                if self.aclient is not None:
                    completion = await self.aclient.chat.completions.create(
                        **self._build_kwargs(prompt, system_prompt=system_prompt)
                    )
                    return _extract_message_text(completion)

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None,
                    lambda: self.generate_response(
                        prompt,
                        max_retries=0,
                        system_prompt=system_prompt,
                    ),
                )
            except Exception as e:
                last_error = str(e)
                attempts += 1
                if attempts > max_retries:
                    print(f"Async LLM call failed after {max_retries + 1} attempts: {last_error}")
                    return None

        return None

    async def aclose(self) -> None:
        if self.aclient is not None:
            try:
                await self.aclient.close()
            except Exception:
                pass

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
