"""Tests for LLMManager — factory method, error handling.

All tests use mock LLM clients to avoid external API calls.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from utils.llm.llm_manager import LLMManager, _create_client
from utils.llm.provider.llm_anthropic import AnthropicClient
from utils.llm.provider.llm_mistral import MistralClient


# ── Construction / validation ────────────────────────────────────────────────

class TestLLMManagerInit:

    def test_valid_construction(self):
        mgr = LLMManager(client=MagicMock())
        assert mgr.client is not None

    def test_no_client(self):
        mgr = LLMManager()
        assert mgr.client is None


# ── generate_response ────────────────────────────────────────────────────────

class TestGenerateResponse:

    @pytest.mark.asyncio
    async def test_async_client(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(return_value="Hello world")
        mgr = LLMManager(client=client)

        result = await mgr.generate_response("prompt")
        assert result == "Hello world"
        client.generate_response_async.assert_called_once_with(
            "prompt", max_retries=1, system_prompt=None
        )

    @pytest.mark.asyncio
    async def test_async_client_with_system_prompt(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(return_value="OK")
        mgr = LLMManager(client=client)

        result = await mgr.generate_response("prompt", system_prompt="system")
        assert result == "OK"
        client.generate_response_async.assert_called_once_with(
            "prompt", max_retries=1, system_prompt="system"
        )

    @pytest.mark.asyncio
    async def test_sync_fallback(self):
        """When client has no async method, falls back to sync in executor."""
        client = MagicMock()
        client.generate_response_async = MagicMock(side_effect=AttributeError)
        client.generate_response = MagicMock(return_value="sync result")
        mgr = LLMManager(client=client)

        result = await mgr.generate_response("prompt")
        assert result == "sync result"

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(side_effect=RuntimeError("API down"))
        mgr = LLMManager(client=client)

        result = await mgr.generate_response("prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_max_retries_forwarded(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(return_value="ok")
        mgr = LLMManager(client=client)

        await mgr.generate_response("prompt", max_retries=5)
        client.generate_response_async.assert_called_once_with(
            "prompt", max_retries=5, system_prompt=None
        )


# ── Factory method ───────────────────────────────────────────────────────────

class TestFromSimulationConfig:

    def test_with_injected_client(self):
        client = MagicMock()
        config = {}
        mgr = LLMManager.from_simulation_config(config, client=client)
        assert mgr.client is client

    def test_role_prefixed_config(self):
        """Role-prefixed keys should be used for the given role."""
        config = {
            "llm_provider": "gemini",
            "director_llm_provider": "anthropic",
            "director_llm_model": "claude-3",
        }
        with patch("utils.llm.llm_manager._create_client") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = LLMManager.from_simulation_config(config, role="director")
            mock_create.assert_called_once_with(
                "anthropic", "claude-3",
                temperature=None, top_p=None, max_tokens=None,
                bsc_model_version=None,
            )

    def test_role_fallback_to_generic(self):
        """When role-prefixed keys missing, fall back to generic."""
        config = {
            "llm_provider": "gemini",
        }
        with patch("utils.llm.llm_manager._create_client_from_config") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = LLMManager.from_simulation_config(config, role="performer")
            mock_create.assert_called_once_with(config)

    def test_no_role_uses_generic(self):
        config = {
            "llm_provider": "gemini",
        }
        with patch("utils.llm.llm_manager._create_client_from_config") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = LLMManager.from_simulation_config(config)
            mock_create.assert_called_once_with(config)


# ── _create_client ───────────────────────────────────────────────────────────

class TestCreateClient:

    def test_unknown_provider_raises(self):
        with pytest.raises(RuntimeError, match="Unknown llm_provider"):
            _create_client("nonexistent_provider")

    def test_default_provider_is_gemini(self):
        """None provider defaults to gemini (routes to GeminiClient)."""
        with patch("utils.llm.provider.llm_gemini.GeminiClient") as MockGemini:
            MockGemini.return_value = MagicMock()
            client = _create_client(None)
            MockGemini.assert_called_once()

    def test_bsc_model_version_only_passed_to_bsc(self):
        with patch("utils.llm.provider.llm_anthropic.AnthropicClient") as MockAnthropic:
            MockAnthropic.return_value = MagicMock()
            _create_client("anthropic", model="claude-3", bsc_model_version="v1")
            assert "bsc_model_version" not in MockAnthropic.call_args.kwargs

        with patch("utils.llm.provider.llm_bsc.BSCClient") as MockBSC:
            MockBSC.return_value = MagicMock()
            _create_client("bsc", model="incivility", bsc_model_version="v1")
            assert MockBSC.call_args.kwargs["bsc_model_version"] == "v1"


class TestProviderTruncationRetries:

    def test_anthropic_retries_with_more_tokens_when_stop_reason_is_max_tokens(self):
        client = AnthropicClient.__new__(AnthropicClient)
        client.model_name = "claude-test"
        client.temperature = None
        client.top_p = None
        client.max_tokens = 256
        client.aclient = None

        first = SimpleNamespace(
            content=[SimpleNamespace(text="Mensaje largo cortado")],
            stop_reason="max_tokens",
        )
        second = SimpleNamespace(
            content=[SimpleNamespace(text="Mensaje largo completo.")],
            stop_reason="end_turn",
        )
        create = MagicMock(side_effect=[first, second])
        client.client = SimpleNamespace(messages=SimpleNamespace(create=create))

        result = client.generate_response("prompt", max_retries=1)

        assert result == "Mensaje largo completo."
        assert create.call_args_list[0].kwargs["max_tokens"] == 256
        assert create.call_args_list[1].kwargs["max_tokens"] > 256

    def test_mistral_retries_with_more_tokens_when_finish_reason_is_length(self):
        client = MistralClient.__new__(MistralClient)
        client.model_name = "mistral-test"
        client.temperature = None
        client.top_p = None
        client.max_tokens = 256

        first = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Mensaje largo cortado"),
                    finish_reason="length",
                )
            ]
        )
        second = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Mensaje largo completo."),
                    finish_reason="stop",
                )
            ]
        )
        complete = MagicMock(side_effect=[first, second])
        client.client = SimpleNamespace(chat=SimpleNamespace(complete=complete))

        result = client.generate_response("prompt", max_retries=1)

        assert result == "Mensaje largo completo."
        assert complete.call_args_list[0].kwargs["max_tokens"] == 256
        assert complete.call_args_list[1].kwargs["max_tokens"] > 256
