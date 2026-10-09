"""documind/core/llm.py
Anthropic LLM wrapper with timeout handling, strict payload constraints, and error mapping.
"""

from __future__ import annotations

import logging
import os

import anthropic

from documind.core.errors import LLMAuthError, LLMUnavailable
from documind.core.types import Usage

logger = logging.getLogger(__name__)


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

        self._client = anthropic.Anthropic(
            api_key=resolved_key.strip(),
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
