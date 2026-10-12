"""tests/test_openai_compat.py -- Unit tests for OpenAICompatLLM and multi-provider factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from documind.core.config import Settings
from documind.core.errors import LLMAuthError, LLMUnavailable
from documind.core.factory import build_default
from documind.core.llm import OpenAICompatLLM


def test_openai_compat_complete_success():
    llm = OpenAICompatLLM(
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key="test-key",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "DocuMind answer [S1]"}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 15},
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        text, usage = llm.complete("system prompt", "user query", max_tokens=100)

    assert text == "DocuMind answer [S1]"
    assert usage.input_tokens == 50
    assert usage.output_tokens == 15


def test_openai_compat_complete_auth_error():
    llm = OpenAICompatLLM(
        model="llama3",
        base_url="http://localhost:11434/v1",
        api_key="bad-key",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("httpx.Client.post", return_value=mock_resp), pytest.raises(LLMAuthError):
        llm.complete("system", "user", max_tokens=100)


def test_openai_compat_complete_unavailable():
    llm = OpenAICompatLLM(
        model="llama3",
        base_url="http://localhost:11434/v1",
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"

    with patch("httpx.Client.post", return_value=mock_resp), pytest.raises(LLMUnavailable):
        llm.complete("system", "user", max_tokens=100)


def test_openai_compat_stream_success():
    import asyncio

    async def _run():
        llm = OpenAICompatLLM(
            model="llama3",
            base_url="http://localhost:11434/v1",
        )

        async def mock_aiter_lines():
            lines = [
                'data: {"choices": [{"delta": {"content": "Docu"}}]}',
                'data: {"choices": [{"delta": {"content": "Mind"}}]}',
                "data: [DONE]",
            ]
            for line in lines:
                yield line

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = mock_aiter_lines

        class MockAsyncContext:
            async def __aenter__(self):
                return mock_resp

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        with patch("httpx.AsyncClient.stream", return_value=MockAsyncContext()):
            collected = []
            async for delta in llm.complete_stream("sys", "usr", max_tokens=50):
                collected.append(delta)

        assert "".join(collected) == "DocuMind"

    asyncio.run(_run())


def test_settings_provider_validation(tmp_path):
    # Valid providers
    for p in ("none", "ollama", "openai_compat", "anthropic"):
        s = Settings(home=tmp_path, llm_provider=p)
        assert s.llm_provider == p

    # Invalid provider
    with pytest.raises(ValueError, match="DOCUMIND_LLM_PROVIDER"):
        Settings(home=tmp_path, llm_provider="invalid_provider")


def test_factory_build_default_retrieval_only(tmp_path):
    s = Settings(home=tmp_path, llm_provider="none")
    engine = build_default(s)
    assert engine.llm is None


def test_factory_build_default_ollama(tmp_path):
    s = Settings(
        home=tmp_path,
        llm_provider="ollama",
        model="llama3",
        openai_base_url="http://localhost:11434/v1",
    )
    engine = build_default(s)
    assert engine.llm is not None
    assert isinstance(engine.llm, OpenAICompatLLM)
    assert engine.llm.model == "llama3"
