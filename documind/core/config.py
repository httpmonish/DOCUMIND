"""documind/core/config.py
Configuration loader for DocuMind settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    home: Path = Path.home() / ".documind"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    chunk_size: int = 200
    overlap: int = 30
    top_k: int = 5
    max_file_mb: int = 50
    max_pages: int = 500
    model: str = "claude-haiku-4-5-20251001"
    min_score: float = 0.35
    max_tokens: int = 600
    llm_timeout_s: float = 20.0
    llm_retries: int = 1
    max_top_k: int = 10
    max_question_chars: int = 2000
    log_questions: bool = False
    api_key: str = ""
    env: str = "dev"
    rate_limit_per_min: int = 20
    max_upload_mb: int = 50
    allow_debug: bool = False

    def __post_init__(self) -> None:
        if not self.model or not self.model.strip():
            raise ValueError("model must not be empty")
        if not (0.0 <= self.min_score <= 1.0):
            raise ValueError(f"min_score must be in [0, 1], got {self.min_score}")
        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")
        if self.llm_timeout_s <= 0:
            raise ValueError(f"llm_timeout_s must be positive, got {self.llm_timeout_s}")
        if self.llm_retries < 0:
            raise ValueError(f"llm_retries must be non-negative, got {self.llm_retries}")
        if self.chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {self.chunk_size}")
        if self.overlap < 0:
            raise ValueError(f"overlap must be non-negative, got {self.overlap}")
        if self.overlap >= self.chunk_size:
            raise ValueError(
                f"DOCUMIND_OVERLAP ({self.overlap}) must be less than "
                f"DOCUMIND_CHUNK_SIZE ({self.chunk_size})"
            )
        if not (1 <= self.top_k <= self.max_top_k):
            raise ValueError(f"top_k must be between 1 and {self.max_top_k}, got {self.top_k}")
        if self.rate_limit_per_min <= 0:
            raise ValueError(f"rate_limit_per_min must be positive, got {self.rate_limit_per_min}")
        if self.max_upload_mb <= 0:
            raise ValueError(f"max_upload_mb must be positive, got {self.max_upload_mb}")
        if self.max_pages <= 0:
            raise ValueError(f"max_pages must be positive, got {self.max_pages}")


def _parse_positive_int(var_name: str, raw_val: str | None, default: int) -> int:
    if raw_val is None or raw_val.strip() == "":
        return default
    try:
        val = int(raw_val)
    except ValueError as err:
        raise ValueError(f"Invalid integer for {var_name}: '{raw_val}'") from err

    if val <= 0:
        raise ValueError(f"{var_name} must be positive, got {val}")
    return val


def _parse_non_negative_int(var_name: str, raw_val: str | None, default: int) -> int:
    if raw_val is None or raw_val.strip() == "":
        return default
    try:
        val = int(raw_val)
    except ValueError as err:
        raise ValueError(f"Invalid integer for {var_name}: '{raw_val}'") from err

    if val < 0:
        raise ValueError(f"{var_name} must be non-negative, got {val}")
    return val


def _parse_positive_float(var_name: str, raw_val: str | None, default: float) -> float:
    if raw_val is None or raw_val.strip() == "":
        return default
    try:
        val = float(raw_val)
    except ValueError as err:
        raise ValueError(f"Invalid float for {var_name}: '{raw_val}'") from err

    if val <= 0:
        raise ValueError(f"{var_name} must be positive, got {val}")
    return val


def _parse_score(var_name: str, raw_val: str | None, default: float) -> float:
    if raw_val is None or raw_val.strip() == "":
        return default
    try:
        val = float(raw_val)
    except ValueError as err:
        raise ValueError(f"Invalid float for {var_name}: '{raw_val}'") from err

    if not (0.0 <= val <= 1.0):
        raise ValueError(f"{var_name} must be in [0, 1], got {val}")
    return val


def _parse_bool(var_name: str, raw_val: str | None, default: bool = False) -> bool:
    if raw_val is None or raw_val.strip() == "":
        return default
    cleaned = raw_val.strip().lower()
    return cleaned in ("1", "true", "yes")


def load_settings() -> Settings:
    """Load configuration from environment variables and .env file."""
    load_dotenv()

    home_env = os.getenv("DOCUMIND_HOME")
    home = Path(home_env).expanduser().resolve() if home_env else Path.home() / ".documind"

    embed_model = os.getenv("DOCUMIND_EMBED_MODEL", "BAAI/bge-small-en-v1.5").strip()
    if not embed_model:
        embed_model = "BAAI/bge-small-en-v1.5"

    chunk_size = _parse_positive_int("DOCUMIND_CHUNK_SIZE", os.getenv("DOCUMIND_CHUNK_SIZE"), 200)
    overlap = _parse_non_negative_int("DOCUMIND_OVERLAP", os.getenv("DOCUMIND_OVERLAP"), 30)
    top_k = _parse_positive_int("DOCUMIND_TOP_K", os.getenv("DOCUMIND_TOP_K"), 5)
    max_file_mb = _parse_positive_int("DOCUMIND_MAX_FILE_MB", os.getenv("DOCUMIND_MAX_FILE_MB"), 50)
    max_pages = _parse_positive_int("DOCUMIND_MAX_PAGES", os.getenv("DOCUMIND_MAX_PAGES"), 500)

    model_env = os.getenv("DOCUMIND_MODEL")
    if model_env is not None and not model_env.strip():
        raise ValueError("DOCUMIND_MODEL must not be empty")
    model = model_env.strip() if model_env else "claude-haiku-4-5-20251001"

    min_score = _parse_score("DOCUMIND_MIN_SCORE", os.getenv("DOCUMIND_MIN_SCORE"), 0.35)
    max_tokens = _parse_positive_int("DOCUMIND_MAX_TOKENS", os.getenv("DOCUMIND_MAX_TOKENS"), 600)
    llm_timeout_s = _parse_positive_float(
        "DOCUMIND_LLM_TIMEOUT_S", os.getenv("DOCUMIND_LLM_TIMEOUT_S"), 20.0
    )
    llm_retries = _parse_non_negative_int(
        "DOCUMIND_LLM_RETRIES", os.getenv("DOCUMIND_LLM_RETRIES"), 1
    )
    log_questions = _parse_bool(
        "DOCUMIND_LOG_QUESTIONS", os.getenv("DOCUMIND_LOG_QUESTIONS"), False
    )

    api_key = os.getenv("DOCUMIND_API_KEY", "").strip()
    env = os.getenv("DOCUMIND_ENV", "dev").strip()
    rate_limit_per_min = _parse_positive_int(
        "DOCUMIND_RATE_LIMIT_PER_MIN", os.getenv("DOCUMIND_RATE_LIMIT_PER_MIN"), 20
    )
    max_upload_mb = _parse_positive_int(
        "DOCUMIND_MAX_UPLOAD_MB", os.getenv("DOCUMIND_MAX_UPLOAD_MB"), max_file_mb
    )
    allow_debug = _parse_bool("DOCUMIND_ALLOW_DEBUG", os.getenv("DOCUMIND_ALLOW_DEBUG"), False)

    return Settings(
        home=home,
        embed_model=embed_model,
        chunk_size=chunk_size,
        overlap=overlap,
        top_k=top_k,
        max_file_mb=max_file_mb,
        max_pages=max_pages,
        model=model,
        min_score=min_score,
        max_tokens=max_tokens,
        llm_timeout_s=llm_timeout_s,
        llm_retries=llm_retries,
        log_questions=log_questions,
        api_key=api_key,
        env=env,
        rate_limit_per_min=rate_limit_per_min,
        max_upload_mb=max_upload_mb,
        allow_debug=allow_debug,
    )
