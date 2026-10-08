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


def load_settings() -> Settings:
    """Load configuration from environment variables and .env file."""
    load_dotenv()

    home_env = os.getenv("DOCUMIND_HOME")
    home = Path(home_env).expanduser().resolve() if home_env else Path.home() / ".documind"

    embed_model = os.getenv("DOCUMIND_EMBED_MODEL", "BAAI/bge-small-en-v1.5").strip()
    if not embed_model:
        embed_model = "BAAI/bge-small-en-v1.5"

    chunk_size = _parse_positive_int("DOCUMIND_CHUNK_SIZE", os.getenv("DOCUMIND_CHUNK_SIZE"), 200)
    overlap = _parse_positive_int("DOCUMIND_OVERLAP", os.getenv("DOCUMIND_OVERLAP"), 30)
    top_k = _parse_positive_int("DOCUMIND_TOP_K", os.getenv("DOCUMIND_TOP_K"), 5)
    max_file_mb = _parse_positive_int("DOCUMIND_MAX_FILE_MB", os.getenv("DOCUMIND_MAX_FILE_MB"), 50)
    max_pages = _parse_positive_int("DOCUMIND_MAX_PAGES", os.getenv("DOCUMIND_MAX_PAGES"), 500)

    if overlap >= chunk_size:
        raise ValueError(
            f"DOCUMIND_OVERLAP ({overlap}) must be less than DOCUMIND_CHUNK_SIZE ({chunk_size})"
        )

    return Settings(
        home=home,
        embed_model=embed_model,
        chunk_size=chunk_size,
        overlap=overlap,
        top_k=top_k,
        max_file_mb=max_file_mb,
        max_pages=max_pages,
    )
