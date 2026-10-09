"""tests/fake_llm.py -- Scripted LLM for pipeline testing."""

from __future__ import annotations

from typing import Any

from documind.core.types import Usage


class FakeLLM:
    """Scripted LLM. `reply` is a string or an Exception instance to raise. Records every call."""

    model_id = "fake-llm"

    def __init__(self, reply: str | Exception = "ok [S1]") -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, Usage(input_tokens=1700, output_tokens=300)
