"""documind/core/llm.py
Anthropic LLM wrapper with timeout handling, strict payload constraints, and error mapping.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator

import anthropic
import httpx

from documind.core.errors import LLMAuthError, LLMUnavailable
from documind.core.types import Usage

logger = logging.getLogger(__name__)


class OpenAICompatLLM:
    """OpenAI-compatible LLM client for Ollama, Groq, Gemini, vLLM, and OpenAI."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "",
        timeout_s: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        self.model = model
        self.model_id = model
        self.base_url = (base_url or "http://localhost:11434/v1").rstrip("/")
        self.api_key = api_key.strip() if api_key else ""
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            headers["HTTP-Referer"] = "https://github.com/DocuMind"
            headers["X-Title"] = "DocuMind"
        return headers

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.post(url, json=payload, headers=self._headers())
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as err:
            raise LLMUnavailable(
                f"Connection to LLM provider at {self.base_url} failed: {err}"
            ) from err
        except Exception as err:
            raise LLMUnavailable(f"LLM request error: {err}") from err

        if resp.status_code in (401, 403):
            raise LLMAuthError(f"LLM authentication failed ({resp.status_code}): {resp.text}")
        if resp.status_code >= 500:
            raise LLMUnavailable(f"LLM server error ({resp.status_code}): {resp.text}")
        if resp.status_code != 200:
            raise LLMUnavailable(f"LLM request returned status {resp.status_code}: {resp.text}")

        try:
            data = resp.json()
            choice = data["choices"][0]
            text = choice.get("message", {}).get("content", "")
            usage_data = data.get("usage", {})
            usage = Usage(
                input_tokens=usage_data.get("prompt_tokens", 0),
                output_tokens=usage_data.get("completion_tokens", 0),
            )
            return text, usage
        except Exception as err:
            raise LLMUnavailable(f"Failed to parse LLM response: {err}") from err

    async def complete_stream(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": True,
        }
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout_s) as client,
                client.stream("POST", url, json=payload, headers=self._headers()) as resp,
            ):
                if resp.status_code in (401, 403):
                    raise LLMAuthError(f"LLM authentication failed ({resp.status_code})")
                if resp.status_code >= 500:
                    raise LLMUnavailable(f"LLM server error ({resp.status_code})")
                if resp.status_code != 200:
                    raise LLMUnavailable(f"LLM request returned status {resp.status_code}")

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    with contextlib.suppress(Exception):
                        chunk_json = json.loads(data_str)
                        delta = chunk_json["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
        except (LLMAuthError, LLMUnavailable):
            raise
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as err:
            raise LLMUnavailable(f"LLM streaming connection failed: {err}") from err
        except Exception as err:
            raise LLMUnavailable(f"LLM streaming failed: {err}") from err


class AnthropicLLM:
    """Production Anthropic client implementing the LLM protocol."""

    def __init__(
        self,
        model: str,
        timeout_s: float,
        max_retries: int,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.model_id = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries

        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_key or not resolved_key.strip():
            raise LLMAuthError(
                "Missing Anthropic API key. Set ANTHROPIC_API_KEY in .env or pass api_key."
            )

        self._api_key = resolved_key.strip()
        self._client = anthropic.Anthropic(
            api_key=self._api_key,
            timeout=timeout_s,
            max_retries=max_retries,
        )

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        """Execute a completion call without temperature, top_p, top_k, or tools."""
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as err:
            raise LLMAuthError(f"Anthropic authentication failed: {err}") from err
        except anthropic.BadRequestError as err:
            err_msg = str(err).lower()
            if "credit balance" in err_msg or "balance is too low" in err_msg:
                raise LLMAuthError(f"Anthropic credit balance exhausted: {err}") from err
            raise
        except (
            anthropic.APITimeoutError,
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as err:
            raise LLMUnavailable(f"Anthropic service unavailable: {err}") from err
        except anthropic.APIStatusError as err:
            if err.status_code >= 500 or err.status_code == 529:
                raise LLMUnavailable(f"Anthropic server error {err.status_code}: {err}") from err
            raise

        blocks: list[str] = []
        for block in response.content:
            text = getattr(block, "text", "")
            if text:
                blocks.append(text)

        full_text = "".join(blocks)
        if not full_text.strip():
            raise LLMUnavailable("Anthropic returned an empty response")

        if response.stop_reason == "max_tokens":
            logger.warning("Anthropic completion reached max_tokens limit")

        usage = Usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return full_text, usage

    async def complete_stream(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        """Stream token deltas using AsyncAnthropic client."""
        client = anthropic.AsyncAnthropic(
            api_key=self._api_key,
            timeout=self.timeout_s,
            max_retries=self.max_retries,
        )
        try:
            async with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as err:
            raise LLMAuthError(f"Anthropic authentication failed: {err}") from err
        except (
            anthropic.APITimeoutError,
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
        ) as err:
            raise LLMUnavailable(f"Anthropic streaming unavailable: {err}") from err
        except Exception as err:
            raise LLMUnavailable(f"Anthropic streaming failed: {err}") from err


class FallbackLLM:
    """Wraps a primary LLM and a fallback LLM.

    If the primary LLM raises LLMUnavailable, seamlessly fails over to the backup LLM.
    """

    def __init__(
        self, primary: OpenAICompatLLM | AnthropicLLM, fallback: OpenAICompatLLM | AnthropicLLM
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.model = getattr(primary, "model", "")
        self.model_id = getattr(primary, "model_id", "")

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        try:
            return self.primary.complete(system, user, max_tokens=max_tokens)
        except LLMUnavailable as err:
            logger.warning(
                "Primary LLM (%s) unavailable: %s. Failing over to backup LLM (%s)...",
                getattr(self.primary, "model", "primary"),
                err,
                getattr(self.fallback, "model", "fallback"),
            )
            return self.fallback.complete(system, user, max_tokens=max_tokens)

    async def complete_stream(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        try:
            async for chunk in self.primary.complete_stream(system, user, max_tokens=max_tokens):
                yield chunk
        except LLMUnavailable as err:
            logger.warning(
                "Primary LLM stream (%s) unavailable: %s. Failing over to backup LLM (%s)...",
                getattr(self.primary, "model", "primary"),
                err,
                getattr(self.fallback, "model", "fallback"),
            )
            async for chunk in self.fallback.complete_stream(system, user, max_tokens=max_tokens):
                yield chunk
