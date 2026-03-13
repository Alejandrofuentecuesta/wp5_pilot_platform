"""Tests for LLMManager — concurrency control, factory method, error handling.

All tests use mock LLM clients to avoid external API calls.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.llm.llm_manager import LLMManager, _create_client


# ── Construction / validation ────────────────────────────────────────────────

class TestLLMManagerInit:

    def test_valid_concurrency_limit(self):
        mgr = LLMManager(concurrency_limit=5, client=MagicMock())
        assert mgr.client is not None

    def test_concurrency_limit_none_raises(self):
        with pytest.raises(RuntimeError, match="must be provided"):
            LLMManager(concurrency_limit=None)

    def test_concurrency_limit_zero_raises(self):
        with pytest.raises(RuntimeError, match="positive integer"):
            LLMManager(concurrency_limit=0)

    def test_concurrency_limit_negative_raises(self):
        with pytest.raises(RuntimeError, match="positive integer"):
            LLMManager(concurrency_limit=-1)

    def test_concurrency_limit_string_raises(self):
        with pytest.raises(RuntimeError, match="must be an integer"):
            LLMManager(concurrency_limit="abc")

    def test_concurrency_limit_string_number(self):
        """String that can be cast to int should work."""
        mgr = LLMManager(concurrency_limit="3", client=MagicMock())
        assert mgr.client is not None

    def test_concurrency_limit_float(self):
        """Float should be castable to int."""
        mgr = LLMManager(concurrency_limit=2.5, client=MagicMock())
        assert mgr.client is not None


# ── generate_response ────────────────────────────────────────────────────────

class TestGenerateResponse:

    @pytest.mark.asyncio
    async def test_async_client(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(return_value="Hello world")
        mgr = LLMManager(concurrency_limit=1, client=client)

        result = await mgr.generate_response("prompt")
        assert result == "Hello world"
        client.generate_response_async.assert_called_once_with(
            "prompt", max_retries=1, system_prompt=None
        )

    @pytest.mark.asyncio
    async def test_async_client_with_system_prompt(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(return_value="OK")
        mgr = LLMManager(concurrency_limit=1, client=client)

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
        mgr = LLMManager(concurrency_limit=1, client=client)

        result = await mgr.generate_response("prompt")
        assert result == "sync result"

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(side_effect=RuntimeError("API down"))
        mgr = LLMManager(concurrency_limit=1, client=client)

        result = await mgr.generate_response("prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_max_retries_forwarded(self):
        client = AsyncMock()
        client.generate_response_async = AsyncMock(return_value="ok")
        mgr = LLMManager(concurrency_limit=1, client=client)

        await mgr.generate_response("prompt", max_retries=5)
        client.generate_response_async.assert_called_once_with(
            "prompt", max_retries=5, system_prompt=None
        )


# ── Semaphore / concurrency ─────────────────────────────────────────────────

class TestConcurrencyControl:

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """With limit=2, only 2 calls should run concurrently."""
        concurrency_high_water = 0
        current = 0

        async def slow_response(prompt, **kwargs):
            nonlocal current, concurrency_high_water
            current += 1
            concurrency_high_water = max(concurrency_high_water, current)
            await asyncio.sleep(0.05)
            current -= 1
            return "ok"

        client = AsyncMock()
        client.generate_response_async = slow_response
        mgr = LLMManager(concurrency_limit=2, client=client)

        tasks = [mgr.generate_response(f"prompt_{i}") for i in range(6)]
        await asyncio.gather(*tasks)

        assert concurrency_high_water <= 2

    @pytest.mark.asyncio
    async def test_semaphore_allows_sequential(self):
        """With limit=1, calls are strictly sequential."""
        call_log = []

        async def tracked_response(prompt, **kwargs):
            call_log.append(("start", prompt))
            await asyncio.sleep(0.01)
            call_log.append(("end", prompt))
            return "ok"

        client = AsyncMock()
        client.generate_response_async = tracked_response
        mgr = LLMManager(concurrency_limit=1, client=client)

        await asyncio.gather(
            mgr.generate_response("A"),
            mgr.generate_response("B"),
        )

        # With limit=1, we should see start-end-start-end pattern
        starts = [i for i, (action, _) in enumerate(call_log) if action == "start"]
        ends = [i for i, (action, _) in enumerate(call_log) if action == "end"]
        # Second start should come after first end
        assert starts[1] > ends[0]


# ── Factory method ───────────────────────────────────────────────────────────

class TestFromSimulationConfig:

    def test_with_injected_client(self):
        client = MagicMock()
        config = {"llm_concurrency_limit": 3}
        mgr = LLMManager.from_simulation_config(config, client=client)
        assert mgr.client is client

    def test_role_prefixed_config(self):
        """Role-prefixed keys should be used for the given role."""
        config = {
            "llm_concurrency_limit": 2,
            "llm_provider": "gemini",
            "director_llm_provider": "anthropic",
            "director_llm_model": "claude-3",
        }
        # We can't actually create a real client without API keys,
        # so we patch _create_client
        with patch("utils.llm.llm_manager._create_client") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = LLMManager.from_simulation_config(config, role="director")
            mock_create.assert_called_once_with(
                "anthropic", "claude-3",
                temperature=None, top_p=None, max_tokens=None,
            )

    def test_role_fallback_to_generic(self):
        """When role-prefixed keys missing, fall back to generic."""
        config = {
            "llm_concurrency_limit": 2,
            "llm_provider": "gemini",
        }
        with patch("utils.llm.llm_manager._create_client_from_config") as mock_create:
            mock_create.return_value = MagicMock()
            mgr = LLMManager.from_simulation_config(config, role="performer")
            mock_create.assert_called_once_with(config)

    def test_no_role_uses_generic(self):
        config = {
            "llm_concurrency_limit": 2,
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

    def test_bsc_provider_routes_to_bsc_client(self):
        with patch("utils.llm.provider.llm_bsc.BSCClient") as MockBSC:
            MockBSC.return_value = MagicMock()
            client = _create_client("bsc", model="incivility")
            MockBSC.assert_called_once_with(model_name="incivility")
