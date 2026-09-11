import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.llm.providers import HttpTextProvider, ProviderError, TokenUsage


@pytest.mark.parametrize("provider,body,expected", [
    ("openai", {"id": "request-1", "choices": [{"message": {"content": "Hello"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 40}, "completion_tokens_details": {"reasoning_tokens": 10}}}, (100, 20, 40)),
    ("qwen", {"choices": [{"message": {"content": "Hello"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}, (100, 20, 0)),
    ("anthropic", {"content": [{"type": "text", "text": "Hello"}], "usage": {"input_tokens": 60, "output_tokens": 20, "cache_read_input_tokens": 40}}, (100, 20, 40)),
    ("gemini", {"candidates": [{"content": {"parts": [{"text": "private thought", "thought": True}, {"text": "Hello"}]}}], "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 12, "thoughtsTokenCount": 8, "cachedContentTokenCount": 40}}, (100, 20, 40)),
])
async def test_provider_payload_and_usage(provider, body, expected, monkeypatch):
    monkeypatch.setattr(settings, f"{provider.upper()}_API_KEY", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "QWEN_BASE_URL", "https://example.test/compatible-mode/v1")
    captured = []
    def handler(request):
        captured.append(request)
        return httpx.Response(200, json=body)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpTextProvider(provider, client).complete("test-model", "system", [{"role": "user", "content": "Hi"}], 256)
    assert result.text == "Hello"
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.cached_tokens) == expected
    payload = json.loads(captured[0].content)
    assert "test-secret" not in str(captured[0].url)
    if provider == "openai":
        assert payload["max_completion_tokens"] == 256 and payload["store"] is False
    elif provider == "qwen":
        assert payload["max_tokens"] == 256 and payload["enable_thinking"] is False
    elif provider == "gemini":
        assert payload["generationConfig"]["maxOutputTokens"] == 256
    else:
        assert payload["max_tokens"] == 256 and payload["system"] == "system"


@pytest.mark.parametrize("status,uncertain", [(400, False), (401, False), (429, False), (408, True), (500, True)])
async def test_http_failure_classification_and_no_retries(status, uncertain, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("secret"))
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "secret response"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            await HttpTextProvider("openai", client).complete("model", "system", [], 100)
    assert error.value.uncertain == uncertain
    assert "secret" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("body", [{}, {"usage": {"prompt_tokens": 1, "completion_tokens": -1}}, {"usage": {"prompt_tokens": "3", "completion_tokens": 2}}])
async def test_bad_usage_is_never_treated_as_free(body, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("secret"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        with pytest.raises(ProviderError) as error:
            await HttpTextProvider("openai", client).complete("model", "system", [], 100)
    assert error.value.uncertain


async def test_timeout_is_uncertain_and_redacts_transport_details(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("secret"))
    def handler(request):
        raise httpx.ReadTimeout("secret URL and customer data", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            await HttpTextProvider("openai", client).complete("model", "system", [], 100)
    assert error.value.uncertain
    assert "secret" not in str(error.value)


def test_inconsistent_cache_usage_is_rejected():
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=10, output_tokens=1, cached_tokens=11)
