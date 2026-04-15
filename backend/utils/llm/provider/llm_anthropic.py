import os
import asyncio
from anthropic import Anthropic, AsyncAnthropic
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
load_dotenv()


def _extract_text(message) -> str:
    parts = []
    for block in getattr(message, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _is_max_tokens_stop(message) -> bool:
    return str(getattr(message, "stop_reason", "") or "").lower() == "max_tokens"


def _expanded_max_tokens(current: int) -> int:
    return min(max(current + 256, int(current * 1.5)), 4096)


class AnthropicClient:
    """Client for interacting with the Anthropic API (sync + async)."""

    def __init__(self, model_name: str = "claude-sonnet-4-6", temperature: float = None, top_p: float = None, max_tokens: int = 1024):
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        api_key = os.getenv("ANTHROPIC_API_KEY")

        # Create sync client
        self.client = Anthropic(api_key=api_key)

        # Create async client
        try:
            self.aclient = AsyncAnthropic(api_key=api_key)
        except Exception:
            self.aclient = None

    def generate_response(self, prompt: str, max_retries: int = 1, system_prompt: str = None) -> Optional[str]:
        """Synchronous response generation."""
        attempts = 0
        last_error = None
        current_max_tokens = self.max_tokens

        while attempts <= max_retries:
            try:
                kwargs = dict(
                    model=self.model_name,
                    max_tokens=current_max_tokens,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                )
                if system_prompt is not None:
                    kwargs["system"] = system_prompt
                if self.temperature is not None:
                    kwargs["temperature"] = self.temperature
                elif self.top_p is not None:
                    kwargs["top_p"] = self.top_p
                message = self.client.messages.create(**kwargs)
                text = _extract_text(message)
                if _is_max_tokens_stop(message):
                    attempts += 1
                    last_error = f"Anthropic response truncated at max_tokens={current_max_tokens}"
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
        """Async response generation using the async Anthropic client when available."""
        attempts = 0
        last_error = None
        current_max_tokens = self.max_tokens

        while attempts <= max_retries:
            try:
                if self.aclient is not None:
                    kwargs = dict(
                        model=self.model_name,
                        max_tokens=current_max_tokens,
                        messages=[
                            {"role": "user", "content": prompt}
                        ],
                    )
                    if system_prompt is not None:
                        kwargs["system"] = system_prompt
                    if self.temperature is not None:
                        kwargs["temperature"] = self.temperature
                    elif self.top_p is not None:
                        kwargs["top_p"] = self.top_p
                    message = await self.aclient.messages.create(**kwargs)
                    text = _extract_text(message)
                    if _is_max_tokens_stop(message):
                        attempts += 1
                        last_error = f"Anthropic response truncated at max_tokens={current_max_tokens}"
                        if attempts > max_retries:
                            print(f"Async LLM call failed after {max_retries + 1} attempts: {last_error}")
                            return None
                        current_max_tokens = _expanded_max_tokens(current_max_tokens)
                        continue
                    return text
                else:
                    # Fallback: run sync client in executor
                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(
                        None, lambda: self.generate_response(prompt, max_retries=0, system_prompt=system_prompt)
                    )
                    return resp

            except Exception as e:
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
