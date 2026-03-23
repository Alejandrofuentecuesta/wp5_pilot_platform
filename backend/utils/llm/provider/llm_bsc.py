import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, OpenAI

load_dotenv()

DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:8888/v1"
DEFAULT_PUBLIC_BASE_URL = "http://212.128.226.126/incivility/api/v1"
DEFAULT_BASE_URLS = (DEFAULT_LOCAL_BASE_URL, DEFAULT_PUBLIC_BASE_URL)
DEFAULT_API_KEYS_FILE = "/etc/incivility-api/api_keys.json"


def _parse_base_urls(raw_value: Optional[str]) -> list[str]:
    """Split a comma-separated env var into ordered candidate base URLs."""
    if not raw_value:
        return []

    values = raw_value.replace("\n", ",").split(",")
    urls: list[str] = []
    for value in values:
        stripped = value.strip().rstrip("/")
        if stripped and stripped not in urls:
            urls.append(stripped)
    return urls


def _resolve_base_urls() -> list[str]:
    """Resolve the ordered list of BSC endpoints to try."""
    configured = _parse_base_urls(os.getenv("BSC_API_BASE_URL"))
    if configured:
        return configured
    return list(DEFAULT_BASE_URLS)


def _load_api_key_from_keys_file(path: str) -> Optional[str]:
    """Load the first enabled API key from the shared incivility API key file."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None

    keys = data.get("keys")
    if not isinstance(keys, dict):
        return None

    for key, meta in keys.items():
        if not isinstance(meta, dict):
            continue
        if not meta.get("enabled", True):
            continue
        stripped = str(key).strip()
        if stripped:
            return stripped

    return None


def _resolve_api_key() -> str:
    """Resolve the API key from env first, then from the shared key file."""
    configured = (os.getenv("BSC_API_KEY") or "").strip()
    if configured:
        return configured

    keys_file = (os.getenv("BSC_API_KEYS_FILE") or DEFAULT_API_KEYS_FILE).strip()
    if not keys_file:
        return ""

    return _load_api_key_from_keys_file(keys_file) or ""


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
        bsc_model_version: str = None,
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.bsc_model_version = bsc_model_version or "v2"  # Default to V2 (recommended)
        self.base_urls = _resolve_base_urls()
        self.base_url = self.base_urls[0]
        self.api_key = _resolve_api_key()
        self.retry_delay_seconds = 1.0

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)

        try:
            self.aclient = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)
        except Exception:
            self.aclient = None

    def _build_kwargs(self, prompt: str, system_prompt: str = None) -> dict:
        # BSC fine-tuned models may not support the "system" role.
        # Merge system instructions into the user message instead.
        if system_prompt is not None:
            combined = f"{system_prompt}\n\n---\n\n{prompt}"
            messages = [{"role": "user", "content": combined}]
        else:
            messages = [{"role": "user", "content": prompt}]

        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.top_p is not None:
            kwargs["top_p"] = self.top_p

        # Pass model_version as extra body parameter for BSC API
        kwargs["extra_body"] = {"model_version": self.bsc_model_version}

        return kwargs

    def _iter_candidate_base_urls(self):
        """Yield the primary base URL first, then any fallbacks."""
        seen: set[str] = set()
        for base_url in [self.base_url, *self.base_urls]:
            if base_url and base_url not in seen:
                seen.add(base_url)
                yield base_url

    def _is_retryable_error(self, error: Exception) -> bool:
        """Return True for transient API errors where another endpoint or retry may help."""
        if isinstance(error, APIConnectionError):
            return True
        if isinstance(error, APIStatusError):
            return error.status_code in {202, 404, 408, 425, 429, 500, 502, 503, 504}
        return False

    def generate_response(
        self,
        prompt: str,
        max_retries: int = 1,
        system_prompt: str = None,
    ) -> Optional[str]:
        attempts = 0
        last_error = None

        while attempts <= max_retries:
            for base_url in self._iter_candidate_base_urls():
                temp_client = None
                try:
                    client = self.client
                    if base_url != self.base_url:
                        temp_client = OpenAI(base_url=base_url, api_key=self.api_key)
                        client = temp_client

                    completion = client.chat.completions.create(
                        **self._build_kwargs(prompt, system_prompt=system_prompt)
                    )
                    return _extract_message_text(completion)
                except Exception as e:
                    last_error = str(e)
                    if not self._is_retryable_error(e):
                        print(f"LLM call failed after {attempts + 1} attempts: {last_error}")
                        return None
                finally:
                    if temp_client is not None:
                        try:
                            temp_client.close()
                        except Exception:
                            pass

            attempts += 1
            if attempts <= max_retries:
                time.sleep(self.retry_delay_seconds)

        print(f"LLM call failed after {max_retries + 1} attempts: {last_error}")
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
            for base_url in self._iter_candidate_base_urls():
                temp_client = None
                try:
                    aclient = self.aclient
                    if base_url != self.base_url:
                        temp_client = AsyncOpenAI(base_url=base_url, api_key=self.api_key)
                        aclient = temp_client

                    if aclient is not None:
                        completion = await aclient.chat.completions.create(
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
                    if not self._is_retryable_error(e):
                        print(f"Async LLM call failed after {attempts + 1} attempts: {last_error}")
                        return None
                finally:
                    if temp_client is not None:
                        try:
                            await temp_client.close()
                        except Exception:
                            pass

            attempts += 1
            if attempts <= max_retries:
                await asyncio.sleep(self.retry_delay_seconds)

        print(f"Async LLM call failed after {max_retries + 1} attempts: {last_error}")
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
