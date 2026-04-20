import asyncio
from typing import Optional


def _tune_bsc_generation_params(
    provider: str,
    temperature: float = None,
    top_p: float = None,
    bsc_model_version: str = None,
):
    """Apply light generation tuning for BSC-hosted models.

    Gemma-based BSC v1 tends to work better with a slightly higher temperature
    so the model can vary its phrasing more naturally and avoid flat,
    repetitive completions.
    """
    provider = (provider or "").lower()
    version = (bsc_model_version or "").lower()

    if provider == "bsc" and version == "v1":
        if temperature is None:
            temperature = 1.1
        else:
            temperature = max(float(temperature), 1.1)

    return temperature, top_p


def _create_client(provider: str, model: str = None, temperature: float = None, top_p: float = None, max_tokens: int = None, bsc_model_version: str = None):
    """Create an LLM client for the given provider and optional model name.

    Imports are done lazily so only the selected provider's package needs to be installed.
    """
    provider = (provider or "gemini").lower()
    temperature, top_p = _tune_bsc_generation_params(
        provider,
        temperature=temperature,
        top_p=top_p,
        bsc_model_version=bsc_model_version,
    )

    kwargs = {}
    if model:
        kwargs["model_name"] = model
    if temperature is not None:
        kwargs["temperature"] = temperature
    if top_p is not None:
        kwargs["top_p"] = top_p
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if provider == "bsc" and bsc_model_version is not None:
        kwargs["bsc_model_version"] = bsc_model_version

    if provider == "huggingface":
        from .provider.llm_huggingface import HuggingFaceClient
        return HuggingFaceClient(**kwargs)
    elif provider == "gemini":
        from .provider.llm_gemini import GeminiClient
        return GeminiClient(**kwargs)
    elif provider == "anthropic":
        from .provider.llm_anthropic import AnthropicClient
        return AnthropicClient(**kwargs)
    elif provider == "mistral":
        from .provider.llm_mistral import MistralClient
        return MistralClient(**kwargs)
    elif provider == "konstanz":
        from .provider.llm_konstanz import KonstanzClient
        return KonstanzClient(**kwargs)
    elif provider == "bsc":
        from .provider.llm_bsc import BSCClient
        return BSCClient(**kwargs)
    elif provider == "none":
        from .local.llm_salamandra import SalamandraClient
        return SalamandraClient(**kwargs)
    else:
        raise RuntimeError(
            "Unknown llm_provider: "
            f"'{provider}'. Supported: 'gemini', 'huggingface', 'anthropic', "
            "'mistral', 'konstanz', 'bsc', 'None' (local)"
        )


def _create_client_from_config(simulation_config: dict):
    """Create the appropriate LLM client based on simulation config.

    Supports both legacy keys (llm_provider/llm_model) and the new
    role-prefixed keys (performer_llm_provider, director_llm_provider).
    When called without a role prefix this returns the Performer client.
    """
    provider = simulation_config.get("llm_provider", "gemini")
    model = simulation_config.get("llm_model")
    temperature = simulation_config.get("temperature")
    top_p = simulation_config.get("top_p")
    max_tokens = simulation_config.get("max_tokens")
    bsc_model_version = simulation_config.get("bsc_model_version")
    return _create_client(provider, model, temperature=temperature, top_p=top_p, max_tokens=max_tokens, bsc_model_version=bsc_model_version)


class LLMManager:
    """Generic LLM manager that delegates calls to an injected client.

    Turns are serialised at the session level (chatroom._turn_lock), so
    there is no need for a per-manager concurrency semaphore.
    """

    def __init__(self, client: Optional[object] = None):
        self.client = client

    @classmethod
    def from_simulation_config(cls, simulation_config: dict, client: Optional[object] = None, role: str = None):
        """Create an LLMManager from a simulation config dict.

        When `role` is provided (e.g. "director" or "performer"), the factory
        looks for role-prefixed keys like `director_llm_provider` / `director_llm_model`.
        Falls back to the generic `llm_provider` / `llm_model` keys.
        """
        if client is None:
            bsc_model_version = simulation_config.get("bsc_model_version")
            if role:
                provider = simulation_config.get(f"{role}_llm_provider")
                model = simulation_config.get(f"{role}_llm_model")
                temperature = simulation_config.get(f"{role}_temperature")
                top_p = simulation_config.get(f"{role}_top_p")
                max_tokens = simulation_config.get(f"{role}_max_tokens")
                if provider:
                    client = _create_client(provider, model, temperature=temperature, top_p=top_p, max_tokens=max_tokens, bsc_model_version=bsc_model_version)
            if client is None:
                client = _create_client_from_config(simulation_config)
        return cls(client=client)

    async def generate_response(self, prompt: str, max_retries: int = 1, system_prompt: str = None) -> Optional[str]:
        """Delegate to the LLM client's async generator.

        Returns the response text or None on failure.
        """
        try:
            # type: ignore[attr-defined]
            return await self.client.generate_response_async(prompt, max_retries=max_retries, system_prompt=system_prompt)
        except AttributeError:
            # Fallback: maybe client only exposes sync API
            # run the sync call in a threadpool
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: self.client.generate_response(prompt, max_retries=max_retries, system_prompt=system_prompt))
        except Exception as e:
            print(f"[LLMManager] generate_response failed: {type(e).__name__}: {e}")
            return None


__all__ = ["LLMManager"]
