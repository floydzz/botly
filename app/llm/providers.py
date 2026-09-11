"""Small HTTP adapters. No automatic retries: an interrupted call may be billable."""

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings


class TokenUsage(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent(self):
        if self.cached_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("cache tokens exceed input tokens")
        return self


@dataclass(frozen=True)
class Completion:
    text: str
    usage: TokenUsage
    raw_usage: dict
    request_id: str | None = None


class ProviderError(Exception):
    def __init__(self, message: str, *, uncertain: bool = True):
        super().__init__(message)
        self.uncertain = uncertain


class TextProvider(Protocol):
    async def complete(self, model: str, system: str, messages: list[dict], max_output: int) -> Completion: ...


def provider_ready(provider: str) -> bool:
    key = getattr(settings, f"{provider.upper()}_API_KEY", None)
    return bool(key and key.get_secret_value()) and (provider != "qwen" or bool(settings.QWEN_BASE_URL))


class HttpTextProvider:
    def __init__(self, provider: str, client: httpx.AsyncClient | None = None):
        if provider not in {"openai", "gemini", "anthropic", "qwen"}:
            raise ProviderError("unsupported language model provider", uncertain=False)
        if not provider_ready(provider):
            raise ProviderError("language model provider is not configured", uncertain=False)
        self.provider, self.client = provider, client

    async def complete(self, model: str, system: str, messages: list[dict], max_output: int) -> Completion:
        key = getattr(settings, f"{self.provider.upper()}_API_KEY").get_secret_value()
        if self.provider == "anthropic":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            payload = {"model": model, "system": system, "messages": messages, "max_tokens": max_output}
        elif self.provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent"
            headers = {"x-goog-api-key": key}
            payload = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages],
                "generationConfig": {"maxOutputTokens": max_output, "candidateCount": 1},
            }
        else:
            base = "https://api.openai.com/v1" if self.provider == "openai" else settings.QWEN_BASE_URL.rstrip("/")
            parsed = urlparse(base)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.query:
                raise ProviderError("provider base URL must be HTTPS", uncertain=False)
            url = base + "/chat/completions"
            headers = {"Authorization": f"Bearer {key}"}
            payload = {"model": model, "messages": [{"role": "system", "content": system}, *messages]}
            payload["max_completion_tokens" if self.provider == "openai" else "max_tokens"] = max_output
            if self.provider == "openai":
                payload["store"] = False
            else:
                # This launch supports Qwen's non-thinking text mode only.
                payload["enable_thinking"] = False

        client = self.client or httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS)
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=settings.LLM_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            # Never persist exception URLs/headers: some providers put credentials in URLs.
            raise ProviderError("provider transport failed; billing needs reconciliation") from None
        finally:
            if self.client is None:
                await client.aclose()
        if response.status_code >= 400:
            raise ProviderError(
                f"provider returned HTTP {response.status_code}",
                uncertain=response.status_code >= 500 or response.status_code == 408,
            )
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("response must be an object")
            if self.provider == "anthropic":
                raw = body["usage"]
                self._check_counts(raw, ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                cached, written = raw.get("cache_read_input_tokens", 0), raw.get("cache_creation_input_tokens", 0)
                # Cache creation should be absent: no cache_control is sent.
                # A future caching implementation must distinguish 5m and 1h writes.
                if written:
                    raise ValueError("unexpected cache creation")
                usage = TokenUsage(input_tokens=raw["input_tokens"] + cached + written, output_tokens=raw["output_tokens"], cached_tokens=cached, cache_write_tokens=written)
                content = "".join(part["text"] for part in body["content"] if part.get("type") == "text")
            elif self.provider == "gemini":
                raw = body["usageMetadata"]
                self._check_counts(raw, ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "cachedContentTokenCount", "totalTokenCount"))
                if raw.get("toolUsePromptTokenCount", 0):
                    raise ValueError("unexpected tool usage")
                output = raw.get("candidatesTokenCount", 0) + raw.get("thoughtsTokenCount", 0)
                if "totalTokenCount" in raw:
                    # Includes thoughts even if their separate count is omitted.
                    total_output = raw["totalTokenCount"] - raw["promptTokenCount"]
                    if total_output < output:
                        raise ValueError("inconsistent total usage")
                    output = total_output
                usage = TokenUsage(input_tokens=raw["promptTokenCount"], output_tokens=output, cached_tokens=raw.get("cachedContentTokenCount", 0))
                if "candidatesTokenCount" not in raw and "totalTokenCount" not in raw:
                    raise ValueError("missing output usage")
                candidates = body.get("candidates") or []
                content = "".join(p.get("text", "") for p in (candidates[0].get("content", {}).get("parts", []) if candidates else []) if not p.get("thought"))
            else:
                raw = body["usage"]
                usage = TokenUsage(input_tokens=raw["prompt_tokens"], output_tokens=raw["completion_tokens"], cached_tokens=(raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
                content = body["choices"][0]["message"].get("content") or ""
            if not isinstance(content, str):
                raise ValueError("invalid content")
            request_id = body.get("id") or response.headers.get("x-request-id") or body.get("responseId")
            return Completion(content.strip(), usage, raw, str(request_id)[:255] if request_id else None)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise ProviderError("provider response or usage was malformed; billing needs reconciliation") from None

    @staticmethod
    def _check_counts(raw, fields):
        for key in fields:
            value = raw.get(key, 0)
            if type(value) is not int or value < 0:
                raise ValueError("invalid token count")
