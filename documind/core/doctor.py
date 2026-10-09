"""documind/core/doctor.py
Environment, dependencies, configuration, and index consistency checks.
Pure diagnostic functions used by 'documind doctor' command.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: str  # "ok", "warn", "fail"
    detail: str
    category: str = "config"  # "config" or "index"

    def __post_init__(self) -> None:
        if self.status not in {"ok", "warn", "fail"}:
            raise ValueError(f"Invalid status: {self.status}")
        if self.category not in {"config", "index"}:
            raise ValueError(f"Invalid category: {self.category}")


def check_python(version_info: tuple[int, ...] | Sequence[int]) -> Check:
    """Check that Python version is at least 3.10."""
    major, minor = version_info[0], version_info[1]
    patch = version_info[2] if len(version_info) > 2 else 0
    version_str = f"{major}.{minor}.{patch}"
    if (major, minor) < (3, 10):
        return Check(
            name="python",
            status="fail",
            detail=f"Python {version_str} < 3.10 required",
            category="config",
        )
    return Check(
        name="python",
        status="ok",
        detail=f"Python {version_str}",
        category="config",
    )


def check_api_key(env: Mapping[str, str]) -> Check:
    """Check whether ANTHROPIC_API_KEY is configured without ever exposing the key."""
    val = env.get("ANTHROPIC_API_KEY")
    if not val or not val.strip():
        return Check(
            name="anthropic key",
            status="warn",
            detail="ANTHROPIC_API_KEY is not set (running in --no-llm mode only)",
            category="config",
        )
    return Check(
        name="anthropic key",
        status="ok",
        detail="ANTHROPIC_API_KEY is set",
        category="config",
    )


def check_home(path: Path) -> Check:
    """Check DocuMind storage home directory."""
    if not path.exists():
        return Check(
            name="home",
            status="warn",
            detail=f"Home directory {path} does not exist yet (will be created on first index)",
            category="config",
        )
    if not path.is_dir():
        return Check(
            name="home",
            status="fail",
            detail=f"Home path {path} is not a directory",
            category="index",
        )
    return Check(
        name="home",
        status="ok",
        detail=f"Home directory exists at {path}",
        category="config",
    )


def check_meta(
    home: Path,
    expected_model: str,
    expected_schema: int = 1,
) -> Check:
    """Check index metadata consistency (model and schema version)."""
    meta_path = home / "meta.json"
    if not meta_path.exists():
        return Check(
            name="index meta",
            status="warn",
            detail="No index metadata found (empty or uninitialized index)",
            category="index",
        )

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as err:
        return Check(
            name="index meta",
            status="fail",
            detail=f"Corrupt meta.json: {err}",
            category="index",
        )

    found_schema = data.get("schema_version")
    if found_schema != expected_schema:
        return Check(
            name="index meta",
            status="fail",
            detail=f"Schema mismatch: index has version {found_schema}, expected {expected_schema}",
            category="index",
        )

    found_model = data.get("embed_model")
    if found_model != expected_model:
        return Check(
            name="index meta",
            status="fail",
            detail=(
                f"Embedding model mismatch: index built with '{found_model}', "
                f"current configuration is '{expected_model}'"
            ),
            category="index",
        )

    return Check(
        name="index meta",
        status="ok",
        detail=f"Index matches model '{expected_model}' and schema {expected_schema}",
        category="index",
    )


def check_extras(
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
) -> list[Check]:
    """Check optional dependencies and extras."""
    results: list[Check] = []

    # 1. Embedder
    if find_spec("sentence_transformers") is not None:
        results.append(
            Check(
                name="embedder",
                status="ok",
                detail="sentence-transformers is installed",
                category="config",
            )
        )
    else:
        results.append(
            Check(
                name="embedder",
                status="fail",
                detail="sentence-transformers missing; install with: pip install 'documind[embed]'",
                category="config",
            )
        )

    # 2. Vector store
    if find_spec("chromadb") is not None:
        results.append(
            Check(
                name="vector store",
                status="ok",
                detail="chromadb is installed",
                category="config",
            )
        )
    else:
        results.append(
            Check(
                name="vector store",
                status="fail",
                detail="chromadb missing; install with: pip install chromadb",
                category="config",
            )
        )

    # 3. LLM client
    if find_spec("anthropic") is not None:
        results.append(
            Check(
                name="llm client",
                status="ok",
                detail="anthropic is installed",
                category="config",
            )
        )
    else:
        results.append(
            Check(
                name="llm client",
                status="fail",
                detail="anthropic missing; install with: pip install anthropic",
                category="config",
            )
        )

    return results


def exit_code(checks: Sequence[Check]) -> int:
    """Compute overall process exit code from diagnostic check results."""
    has_index_fail = any(c.status == "fail" and c.category == "index" for c in checks)
    if has_index_fail:
        return 6
    has_config_fail = any(c.status == "fail" for c in checks)
    if has_config_fail:
        return 5
    return 0
