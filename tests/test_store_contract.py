"""tests/test_store_contract.py
Runs store contract tests against both NumpyStore and ChromaStore.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from documind.core.vector_store import ChromaStore, NumpyStore
from tests.store_contract import ALL_CHECKS


@pytest.fixture(params=["numpy", "chroma"])
def store(request: Any, tmp_path: Path) -> Any:
    if request.param == "numpy":
        return NumpyStore(dim=384)
    return ChromaStore(tmp_path / "chroma", "bge-small-en-v1.5", 384)


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda f: f.__name__)
def test_store_contract(store: Any, check: Any) -> None:
    check(store)


def test_core_does_not_use_http_client_or_chroma_run() -> None:
    core_dir = Path("documind/core")
    for py_file in core_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "HttpClient" not in content, f"Forbidden 'HttpClient' found in {py_file}"
        assert "chroma run" not in content, f"Forbidden 'chroma run' found in {py_file}"
