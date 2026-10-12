"""documind/core/factory.py
Default engine wiring for DocuMind.
"""

from __future__ import annotations

import logging
import os

from documind.core.config import Settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.errors import LLMAuthError
from documind.core.llm import AnthropicLLM, FallbackLLM, OpenAICompatLLM
from documind.core.pipeline import DocuMind
from documind.core.vector_store import ChromaStore

logger = logging.getLogger(__name__)


def build_default(settings: Settings) -> DocuMind:
    """Wire default SentenceTransformer embedder, persistent ChromaStore, and configured LLM.

    Supports providers: 'none' (retrieval-only), 'anthropic', 'ollama', 'openai_compat'.
    """
    embedder = SentenceTransformerEmbedder(model_id=settings.embed_model)
    store = ChromaStore(
        path=settings.home / "chroma",
        model_slug=embedder.model_id,
        dim=embedder.dim,
    )

    llm: AnthropicLLM | OpenAICompatLLM | FallbackLLM | None = None
    provider = settings.llm_provider.lower()

    if provider == "none":
        logger.info("Running in zero-key retrieval-only mode (DOCUMIND_LLM_PROVIDER=none).")
    elif provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY") or settings.api_key
        if api_key and api_key.strip():
            try:
                llm = AnthropicLLM(
                    model=settings.model,
                    timeout_s=settings.llm_timeout_s,
                    max_retries=settings.llm_retries,
                    api_key=api_key.strip(),
                )
            except LLMAuthError as err:
                logger.warning(
                    "Could not initialize Anthropic LLM: %s. Running retrieval-only.", err
                )
                llm = None
        else:
            logger.warning("ANTHROPIC_API_KEY not configured. Running in retrieval-only mode.")
    elif provider in ("ollama", "openai_compat", "gemini", "openrouter"):
        base_url = settings.openai_base_url or (
            "https://openrouter.ai/api/v1"
            if provider == "openrouter"
            else (
                "https://generativelanguage.googleapis.com/v1beta/openai/"
                if provider == "gemini"
                else (
                    "http://localhost:11434/v1"
                    if provider == "ollama"
                    else "https://api.openai.com/v1"
                )
            )
        )
        api_key = (
            settings.openai_api_key
            or (
                (settings.openrouter_api_key or os.getenv("OPENROUTER_API_KEY"))
                if provider == "openrouter"
                else (
                    os.getenv("GEMINI_API_KEY")
                    if provider == "gemini"
                    else os.getenv("OPENAI_API_KEY")
                )
            )
            or ("ollama" if provider == "ollama" else "")
        )
        try:
            llm = OpenAICompatLLM(
                model=settings.model,
                base_url=base_url,
                api_key=api_key,
                timeout_s=settings.llm_timeout_s,
                max_retries=settings.llm_retries,
            )
            logger.info(
                "Initialized %s LLM client at %s (model: %s)",
                provider,
                base_url,
                settings.model,
            )

            # Configure failover if secondary key is present
            openrouter_key = os.getenv("OPENROUTER_API_KEY") or settings.openrouter_api_key
            gemini_key = os.getenv("GEMINI_API_KEY")
            if provider == "gemini" and openrouter_key:
                backup_llm = OpenAICompatLLM(
                    model=os.getenv("DOCUMIND_FALLBACK_MODEL", "meta-llama/llama-3.1-8b-instruct"),
                    base_url="https://openrouter.ai/api/v1",
                    api_key=openrouter_key,
                    timeout_s=settings.llm_timeout_s,
                    max_retries=settings.llm_retries,
                )
                llm = FallbackLLM(llm, backup_llm)
                logger.info("Configured OpenRouter as failover fallback for Gemini.")
            elif provider == "openrouter" and gemini_key:
                backup_llm = OpenAICompatLLM(
                    model=os.getenv("DOCUMIND_FALLBACK_MODEL", "gemini-3.5-flash"),
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=gemini_key,
                    timeout_s=settings.llm_timeout_s,
                    max_retries=settings.llm_retries,
                )
                llm = FallbackLLM(llm, backup_llm)
                logger.info("Configured Gemini as failover fallback for OpenRouter.")
        except Exception as err:
            logger.warning(
                "Could not initialize %s LLM: %s. Running retrieval-only.",
                provider,
                err,
            )
            llm = None

    return DocuMind(settings, embedder, store, llm)
