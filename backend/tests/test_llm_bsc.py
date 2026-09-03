import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.llm.provider.llm_bsc import (
    DEFAULT_LOCAL_BASE_URL,
    _extract_message_text,
    _load_api_key_from_keys_file,
    _resolve_base_urls,
)


def _completion(*, content=None, reasoning_content=None):
    message = SimpleNamespace(
        content=content,
        model_extra={"reasoning_content": reasoning_content},
    )
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


class TestExtractMessageText:
    def test_prefers_content_when_present(self):
        completion = _completion(content="Clean reply", reasoning_content="Other reply")
        assert _extract_message_text(completion) == "Clean reply"

    def test_falls_back_to_reasoning_content(self):
        completion = _completion(content="", reasoning_content="Recovered reply")
        assert _extract_message_text(completion) == "Recovered reply"

    def test_handles_segmented_content(self):
        completion = _completion(content=[{"text": "First line"}, {"text": "Second line"}])
        assert _extract_message_text(completion) == "First line\nSecond line"

    def test_returns_none_when_no_text(self):
        completion = _completion(content="", reasoning_content="")
        assert _extract_message_text(completion) is None


class TestBaseUrlResolution:
    def test_defaults_to_loopback_only(self):
        """No plain-HTTP public fallback: prompts and the API key would
        travel in cleartext."""
        with patch.dict("os.environ", {"BSC_API_BASE_URL": ""}, clear=False):
            assert _resolve_base_urls() == [DEFAULT_LOCAL_BASE_URL]

    def test_https_env_urls_are_accepted_in_order(self):
        with patch.dict("os.environ", {"BSC_API_BASE_URL": "https://a.test/v1, https://b.test/v1"}, clear=False):
            assert _resolve_base_urls() == ["https://a.test/v1", "https://b.test/v1"]

    def test_loopback_http_is_accepted(self):
        with patch.dict("os.environ", {"BSC_API_BASE_URL": "http://127.0.0.1:8888/v1"}, clear=False):
            assert _resolve_base_urls() == ["http://127.0.0.1:8888/v1"]

    def test_public_http_urls_are_dropped(self):
        with patch.dict("os.environ", {"BSC_API_BASE_URL": "http://212.128.226.126/incivility/api/v1, https://ok.test/v1"}, clear=False):
            assert _resolve_base_urls() == ["https://ok.test/v1"]

    def test_all_insecure_config_falls_back_to_loopback_default(self):
        with patch.dict("os.environ", {"BSC_API_BASE_URL": "http://evil.test/v1"}, clear=False):
            assert _resolve_base_urls() == [DEFAULT_LOCAL_BASE_URL]


class TestApiKeyLoading:
    def test_loads_first_enabled_key_from_keys_file(self, tmp_path: Path):
        keys_file = tmp_path / "api_keys.json"
        keys_file.write_text(json.dumps({
            "keys": {
                "disabled-key": {"enabled": False},
                "enabled-key": {"enabled": True},
            }
        }))

        assert _load_api_key_from_keys_file(str(keys_file)) == "enabled-key"
