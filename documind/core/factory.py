"""documind/core/factory.py
Default engine wiring for DocuMind.
"""

from __future__ import annotations

import logging
import os

from documind.core.config import Settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.errors import LLMAuthError
from documind.core.llm import AnthropicLLM
from documind.core.pipeline import DocuMind
from documind.core.vector_store import ChromaStore

logger = logging.getLogger(__name__)


def build_default(settings: Settings) -> DocuMind:
    """Wire default SentenceTransformer embedder, persistent ChromaStore, and AnthropicLLM.

    If ANTHROPIC_API_KEY is missing or invalid, logs a warning and runs retrieval-only.
    """
    embedder = SentenceTransformerEmbedder(model_id=settings.embed_model)
    store = ChromaStore(
        path=settings.home / "chroma",
        model_slug=embedder.model_id,
        dim=embedder.dim,
    )

    llm: AnthropicLLM | None = None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key and api_key.strip():
        try:
            llm = AnthropicLLM(
                model=settings.model,
                timeout_s=settings.llm_timeout_s,
                max_retries=settings.llm_retries,
                api_key=api_key.strip(),
            )
        except LLMAuthError as err:
            logger.warning("Could not initialize Anthropic LLM: %s. Running retrieval-only.", err)
            llm = None
    else:
        logger.warning("ANTHROPIC_API_KEY not configured. Running in retrieval-only mode.")

    return DocuMind(settings, embedder, store, llm)
