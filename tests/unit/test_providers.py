"""Unit tests for libs.adapters.llm.providers."""

from __future__ import annotations

from libs.adapters.llm.providers import (
    build_headers,
    build_payload,
    extract_content,
    get_endpoint,
    get_query_params,
)

# ---------------------------------------------------------------------------
# OpenAI-compatible
# ---------------------------------------------------------------------------


class TestOpenAICompatible:
    def test_build_payload_basic(self):
        payload = build_payload(
            "openai_compatible", "model-x",
            [{"role": "user", "content": "hi"}],
            temperature=0.5, max_tokens=100, json_mode=False,
        )
        assert payload["model"] == "model-x"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 100
        assert "response_format" not in payload

    def test_build_payload_json_mode(self):
        payload = build_payload(
            "openai_compatible", "m",
            [{"role": "user", "content": "hi"}],
            temperature=0.3, max_tokens=512, json_mode=True,
        )
        assert payload["response_format"] == {"type": "json_object"}

    def test_build_headers_with_key(self):
        headers = build_headers("openai_compatible", "sk-test")
        assert headers["Authorization"] == "Bearer sk-test"
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_without_key(self):
        headers = build_headers("openai_compatible", None)
        assert "Authorization" not in headers

    def test_get_endpoint(self):
        url = get_endpoint("openai_compatible", "http://localhost:1234/v1", "m")
        assert url == "http://localhost:1234/v1/chat/completions"

    def test_extract_content(self):
        data = {"choices": [{"message": {"content": "hello world"}}]}
        assert extract_content("openai_compatible", data) == "hello world"

    def test_extract_content_empty_choices(self):
        assert extract_content("openai_compatible", {"choices": []}) == ""
        assert extract_content("openai_compatible", {}) == ""


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


class TestAnthropic:
    def test_build_payload_separates_system(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        payload = build_payload(
            "anthropic", "claude-3-haiku",
            messages, temperature=0.3, max_tokens=512, json_mode=False,
        )
        assert payload["system"] == "You are helpful."
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"

    def test_build_payload_json_mode_prefill(self):
        messages = [{"role": "user", "content": "Give me JSON"}]
        payload = build_payload(
            "anthropic", "claude-3-haiku",
            messages, temperature=0.3, max_tokens=512, json_mode=True,
        )
        assert payload["messages"][-1]["role"] == "assistant"
        assert payload["messages"][-1]["content"] == "{"

    def test_build_headers(self):
        headers = build_headers("anthropic", "sk-ant-test")
        assert headers["x-api-key"] == "sk-ant-test"
        assert headers["anthropic-version"] == "2023-06-01"

    def test_get_endpoint(self):
        url = get_endpoint("anthropic", "https://api.anthropic.com/v1", "m")
        assert url == "https://api.anthropic.com/v1/messages"

    def test_extract_content(self):
        data = {"content": [{"type": "text", "text": "hello"}]}
        assert extract_content("anthropic", data) == "hello"

    def test_extract_content_empty(self):
        assert extract_content("anthropic", {"content": []}) == ""


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


class TestGoogle:
    def test_build_payload_converts_messages(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        payload = build_payload(
            "google", "gemini-pro",
            messages, temperature=0.3, max_tokens=512, json_mode=False,
        )
        assert payload["systemInstruction"]["parts"][0]["text"] == "You are helpful."
        assert len(payload["contents"]) == 2
        assert payload["contents"][0]["role"] == "user"
        assert payload["contents"][1]["role"] == "model"

    def test_build_payload_json_mode(self):
        payload = build_payload(
            "google", "gemini-pro",
            [{"role": "user", "content": "hi"}],
            temperature=0.3, max_tokens=512, json_mode=True,
        )
        assert payload["generationConfig"]["responseMimeType"] == "application/json"

    def test_get_endpoint(self):
        url = get_endpoint(
            "google",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-pro",
        )
        assert "gemini-pro:generateContent" in url

    def test_extract_content(self):
        data = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "hello"}],
                },
            }],
        }
        assert extract_content("google", data) == "hello"

    def test_get_query_params_with_key(self):
        params = get_query_params("google", "my-key")
        assert params == {"key": "my-key"}

    def test_get_query_params_openai(self):
        params = get_query_params("openai_compatible", "sk-test")
        assert params == {}


# ---------------------------------------------------------------------------
# Unsupported provider
# ---------------------------------------------------------------------------


class TestUnsupported:
    def test_build_payload_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unsupported provider"):
            build_payload("unknown", "m", [], 0.3, 512, False)

    def test_extract_content_raises(self):
        import pytest

        with pytest.raises(ValueError, match="Unsupported provider"):
            extract_content("unknown", {})
