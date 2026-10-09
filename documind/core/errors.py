"""documind/core/errors.py
Domain error hierarchy for DocuMind.
"""

from __future__ import annotations


class DocuMindError(Exception):
    """Base error for all expected domain failures in DocuMind."""


class DocumentUnreadable(DocuMindError):
    """Raised when a document cannot be parsed or read."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"Failed to read '{source}': {reason}")
        self.source = source
        self.reason = reason


class DocumentTooLarge(DocuMindError):
    """Raised when a file exceeds size or page limits."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"Document '{source}' too large: {reason}")
        self.source = source
        self.reason = reason


class EmbeddingFailed(DocuMindError):
    """Raised when the embedding model fails or runs out of memory."""


class IndexUnavailable(DocuMindError):
    """Raised when the vector index cannot be accessed or is corrupted."""


class LLMUnavailable(DocuMindError):
    """Raised on LLM timeout, 429, 5xx, connection failure, or empty reply."""


class LLMAuthError(DocuMindError):
    """Raised on 401, 403, missing key, or exhausted credit."""
