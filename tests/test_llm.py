"""tests/test_llm.py -- Unit tests for AnthropicLLM (offline, mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock

import anthropic
import pytest

from documind.core.errors import LLMAuthError, LLMUnavailable
from documind.core.llm import AnthropicLLM


def test_missing_api_key_raises_auth_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(LLMAuthError, match="Missing Anthropic API key"):
        AnthropicLLM(model="claude-haiku-4-5-20251001", timeout_s=10.0, max_retries=1, api_key="")


def test_complete_passes_exact_parameters_and_no_forbidden_kwargs():
    llm = AnthropicLLM(
        model="claude-haiku-4-5-20251001",
        timeout_s=15.0,
        max_retries=1,
        api_key="test-key",
    )
    mock_response = MagicMock()
    mock_block = MagicMock()
    mock_block.text = "Hello world [S1]"
    mock_response.content = [mock_block]
    mock_response.stop_reason = "end_turn"
    mock_response.usage.input_tokens = 120
    mock_response.usage.output_tokens = 30

    llm._client.messages.create = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    reply, usage = llm.complete(system="System instructions", user="User question", max_tokens=250)

    assert reply == "Hello world [S1]"
    assert usage.input_tokens == 120
    assert usage.output_tokens == 30

    call_kwargs = llm._client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call_kwargs["max_tokens"] == 250
    assert call_kwargs["system"] == "System instructions"
    assert call_kwargs["messages"] == [{"role": "user", "content": "User question"}]

    for forbidden in ("tools", "temperature", "top_p", "top_k"):
        assert forbidden not in call_kwargs, f"{forbidden} must not be passed"


def test_empty_response_raises_llm_unavailable():
    llm = AnthropicLLM(
        model="claude-haiku-4-5-20251001",
        timeout_s=10.0,
        max_retries=1,
        api_key="test-key",
    )
    mock_response = MagicMock()
    mock_response.content = []
    mock_response.stop_reason = "end_turn"
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 0
    llm._client.messages.create = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    with pytest.raises(LLMUnavailable, match="empty response"):
        llm.complete(system="sys", user="usr", max_tokens=100)


@pytest.mark.parametrize(
    "exc_cls,target_error",
    [
        (anthropic.AuthenticationError, LLMAuthError),
        (anthropic.PermissionDeniedError, LLMAuthError),
        (anthropic.APITimeoutError, LLMUnavailable),
        (anthropic.APIConnectionError, LLMUnavailable),
        (anthropic.RateLimitError, LLMUnavailable),
        (anthropic.InternalServerError, LLMUnavailable),
    ],
)
def test_error_mapping_to_domain_errors(exc_cls, target_error):
    llm = AnthropicLLM(
        model="claude-haiku-4-5-20251001",
        timeout_s=10.0,
        max_retries=1,
        api_key="test-key",
    )
    mock_req = MagicMock()
    if issubclass(exc_cls, anthropic.APIStatusError):
        err_instance = exc_cls(message="failed", response=MagicMock(status_code=500), body={})
    elif exc_cls is anthropic.APIConnectionError or exc_cls is anthropic.APITimeoutError:
        err_instance = exc_cls(request=mock_req)
    else:
        err_instance = exc_cls(message="failed", response=MagicMock(), body={})

    llm._client.messages.create = MagicMock(side_effect=err_instance)  # type: ignore[method-assign]

    with pytest.raises(target_error):
        llm.complete(system="s", user="u", max_tokens=100)


def test_bad_request_credit_exhausted_maps_to_auth_error():
    llm = AnthropicLLM(
        model="claude-haiku-4-5-20251001",
        timeout_s=10.0,
        max_retries=1,
        api_key="test-key",
    )
    err = anthropic.BadRequestError(
        message="Your credit balance is too low to access the Claude API.",
        response=MagicMock(status_code=400),
        body={},
    )
    llm._client.messages.create = MagicMock(side_effect=err)  # type: ignore[method-assign]

    with pytest.raises(LLMAuthError, match="credit balance exhausted"):
        llm.complete(system="s", user="u", max_tokens=100)


def test_other_4xx_reraised_unchanged():
    llm = AnthropicLLM(
        model="claude-haiku-4-5-20251001",
        timeout_s=10.0,
        max_retries=1,
        api_key="test-key",
    )
    err = anthropic.BadRequestError(
        message="invalid prompt format",
        response=MagicMock(status_code=400),
        body={},
    )
    llm._client.messages.create = MagicMock(side_effect=err)  # type: ignore[method-assign]

    with pytest.raises(anthropic.BadRequestError):
        llm.complete(system="s", user="u", max_tokens=100)
