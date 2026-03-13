from types import SimpleNamespace

from utils.llm.provider.llm_bsc import _extract_message_text


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
