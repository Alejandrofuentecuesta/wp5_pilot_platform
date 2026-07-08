import os
import asyncio
import json as _json
import random as _random
import time as _time
from openai import OpenAI, AsyncOpenAI
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
load_dotenv()

BASE_URL = "https://whatif.inf.uni-konstanz.de/v1"

_MOCK_LLM = os.getenv("MOCK_LLM", "").lower() in ("1", "true", "yes")


def _log_usage(provider: str, model: str, completion, latency: float) -> None:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return
    entry = {
        "provider": provider,
        "model": model,
        "input_tokens": getattr(usage, "prompt_tokens", 0),
        "output_tokens": getattr(usage, "completion_tokens", 0),
        "latency_s": round(latency, 3),
    }
    print(f"[LLM_USAGE] {_json.dumps(entry)}", flush=True)

def _log_error(provider: str, model: str, error: str, latency: float) -> None:
    entry = {
        "provider": provider,
        "model": model,
        "error": error,
        "latency_s": round(latency, 3),
    }
    print(f"[LLM_ERROR] {_json.dumps(entry)}", flush=True)


class KonstanzClient:
    """Client for the University of Konstanz vLLM endpoint (OpenAI-compatible)."""

    def __init__(self, model_name: str = "BSC-LT/ALIA-40b-instruct-2601", temperature: float = None, top_p: float = None, max_tokens: int = 1024):
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        api_key = os.getenv("KONSTANZ_API_KEY", "")

        self.client = OpenAI(base_url=BASE_URL, api_key=api_key)

        try:
            self.aclient = AsyncOpenAI(base_url=BASE_URL, api_key=api_key)
        except Exception:
            self.aclient = None

    def generate_response(self, prompt: str, max_retries: int = 1, system_prompt: str = None) -> Optional[str]:
        """Synchronous response generation."""
        if _MOCK_LLM:
            delay = _random.uniform(0.5, 1.5)
            _time.sleep(delay)
            print(f"[LLM_USAGE] {_json.dumps({'provider': 'konstanz', 'model': self.model_name, 'input_tokens': 0, 'output_tokens': 0, 'mock': True, 'latency_s': round(delay, 3)})}", flush=True)
            return None
        attempts = 0
        last_error = None

        while attempts <= max_retries:
            try:
                messages = []
                if system_prompt is not None:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                kwargs = dict(
                    model=self.model_name,
                    messages=messages,
                )
                if self.temperature is not None:
                    kwargs["temperature"] = self.temperature
                if self.top_p is not None:
                    kwargs["top_p"] = self.top_p
                kwargs["max_tokens"] = self.max_tokens
                t0 = _time.monotonic()
                completion = self.client.chat.completions.create(**kwargs)
                _log_usage("konstanz", self.model_name, completion, _time.monotonic() - t0)
                return completion.choices[0].message.content

            except Exception as e:
                elapsed = _time.monotonic() - t0 if 't0' in locals() else 0
                _log_error("konstanz", self.model_name, str(e), elapsed)
                last_error = str(e)
                attempts += 1

                if attempts > max_retries:
                    print(f"LLM call failed after {max_retries + 1} attempts: {last_error}")
                    return None

        return None

    async def generate_response_async(self, prompt: str, max_retries: int = 1, system_prompt: str = None) -> Optional[str]:
        """Async response generation using the async OpenAI client when available."""
        if _MOCK_LLM:
            delay = _random.uniform(0.5, 1.5)
            await asyncio.sleep(delay)
            print(f"[LLM_USAGE] {_json.dumps({'provider': 'konstanz', 'model': self.model_name, 'input_tokens': 0, 'output_tokens': 0, 'mock': True, 'latency_s': round(delay, 3)})}", flush=True)
            return None
        attempts = 0
        last_error = None

        while attempts <= max_retries:
            try:
                if self.aclient is not None:
                    messages = []
                    if system_prompt is not None:
                        messages.append({"role": "system", "content": system_prompt})
                    messages.append({"role": "user", "content": prompt})
                    kwargs = dict(
                        model=self.model_name,
                        messages=messages,
                    )
                    if self.temperature is not None:
                        kwargs["temperature"] = self.temperature
                    if self.top_p is not None:
                        kwargs["top_p"] = self.top_p
                    kwargs["max_tokens"] = self.max_tokens
                    t0 = _time.monotonic()
                    completion = await self.aclient.chat.completions.create(**kwargs)
                    _log_usage("konstanz", self.model_name, completion, _time.monotonic() - t0)
                    return completion.choices[0].message.content
                else:
                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(
                        None, lambda: self.generate_response(prompt, max_retries=0, system_prompt=system_prompt)
                    )
                    return resp

            except Exception as e:
                elapsed = _time.monotonic() - t0 if 't0' in locals() else 0
                _log_error("konstanz", self.model_name, str(e), elapsed)
                last_error = str(e)
                attempts += 1

                if attempts > max_retries:
                    print(f"Async LLM call failed after {max_retries + 1} attempts: {last_error}")
                    return None

        return None

    async def aclose(self) -> None:
        """Close the async client if present."""
        if self.aclient is not None:
            try:
                await self.aclient.close()
            except Exception:
                pass

    def close(self) -> None:
        """Close the sync client."""
        try:
            self.client.close()
        except Exception:
            pass
