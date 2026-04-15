import os
import asyncio
from mistralai.client import Mistral
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
load_dotenv()


def _extract_text(choice) -> str:
    content = getattr(getattr(choice, "message", None), "content", "")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts).strip()
    return (content or "").strip()


def _is_max_tokens_stop(choice) -> bool:
    reason = str(getattr(choice, "finish_reason", "") or "").lower()
    return reason in {"length", "max_tokens"}


def _expanded_max_tokens(current: int) -> int:
    return min(max(current + 256, int(current * 1.5)), 4096)


class MistralClient:
    """Client for interacting with the Mistral API (sync + async)."""

    def __init__(self, model_name: str = "mistral-large-latest", temperature: float = None, top_p: float = None, max_tokens: int = 1024):
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        api_key = os.getenv("MISTRAL_API_KEY")

        self.client = Mistral(api_key=api_key)

    def generate_response(self, prompt: str, max_retries: int = 1, system_prompt: str = None) -> Optional[str]:
        """Synchronous response generation."""
        attempts = 0
        last_error = None
        current_max_tokens = self.max_tokens

        while attempts <= max_retries:
            try:
                messages = []
                if system_prompt is not None:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                kwargs = dict(
                    model=self.model_name,
                    messages=messages,
                    safe_prompt=False,
                )
                if self.temperature is not None:
                    kwargs["temperature"] = self.temperature
                if self.top_p is not None:
                    kwargs["top_p"] = self.top_p
                kwargs["max_tokens"] = current_max_tokens
                response = self.client.chat.complete(**kwargs)
                choice = response.choices[0]
                text = _extract_text(choice)
                if _is_max_tokens_stop(choice):
                    attempts += 1
                    last_error = f"Mistral response truncated at max_tokens={current_max_tokens}"
                    if attempts > max_retries:
                        print(f"LLM call failed after {max_retries + 1} attempts: {last_error}")
                        return None
                    current_max_tokens = _expanded_max_tokens(current_max_tokens)
                    continue
                return text

            except Exception as e:
                last_error = str(e)
                attempts += 1

                if attempts > max_retries:
                    print(f"LLM call failed after {max_retries + 1} attempts: {last_error}")
                    return None

        return None

    async def generate_response_async(self, prompt: str, max_retries: int = 1, system_prompt: str = None) -> Optional[str]:
        """Async response generation using the Mistral async methods."""
        attempts = 0
        last_error = None
        current_max_tokens = self.max_tokens

        while attempts <= max_retries:
            try:
                messages = []
                if system_prompt is not None:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                kwargs = dict(
                    model=self.model_name,
                    messages=messages,
                    safe_prompt=False,
                )
                if self.temperature is not None:
                    kwargs["temperature"] = self.temperature
                if self.top_p is not None:
                    kwargs["top_p"] = self.top_p
                kwargs["max_tokens"] = current_max_tokens
                response = await self.client.chat.complete_async(**kwargs)
                choice = response.choices[0]
                text = _extract_text(choice)
                if _is_max_tokens_stop(choice):
                    attempts += 1
                    last_error = f"Mistral response truncated at max_tokens={current_max_tokens}"
                    if attempts > max_retries:
                        print(f"Async LLM call failed after {max_retries + 1} attempts: {last_error}")
                        return None
                    current_max_tokens = _expanded_max_tokens(current_max_tokens)
                    continue
                return text

            except Exception as e:
                last_error = str(e)
                attempts += 1

                if attempts > max_retries:
                    print(f"Async LLM call failed after {max_retries + 1} attempts: {last_error}")
                    return None

        return None

    async def aclose(self) -> None:
        """Close the client (Mistral SDK close is sync)."""
        try:
            self.client.close()
        except Exception:
            pass

    def close(self) -> None:
        """Close the sync client."""
        try:
            self.client.close()
        except Exception:
            pass
