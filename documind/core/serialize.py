"""documind/core/serialize.py
Shared JSON serialization contracts for CLI, REST, and MCP interfaces.
Converts engine dataclasses into plain JSON-serializable dictionaries.
"""

from __future__ import annotations

from typing import Any

from documind.core.ingest import IndexReport
from documind.core.types import Answer, RetrievedChunk


def retrieved_to_dict(
    rc: RetrievedChunk,
    *,
    include_text: bool = False,
) -> dict[str, Any]:
    """Serialize a RetrievedChunk to a plain dictionary."""
    d: dict[str, Any] = {
        "id": rc.chunk.id,
        "source": rc.chunk.source,
        "chunk_index": int(rc.chunk.chunk_index),
        "score": round(float(rc.score), 4),
        "rank": int(rc.rank),
        "snippet": rc.chunk.text[:200],
    }
    if include_text:
        d["text"] = rc.chunk.text
    return d


def answer_to_dict(
    ans: Answer,
    *,
    include_retrieved: bool = False,
) -> dict[str, Any]:
    """Serialize an Answer dataclass to a stable plain dictionary."""
    citations_list = [
        {
            "marker": c.marker,
            "source": c.source,
            "chunk_index": int(c.chunk_index),
            "snippet": c.snippet,
            "score": round(float(c.score), 4),
        }
        for c in ans.citations
    ]

    d: dict[str, Any] = {
        "text": ans.text,
        "outcome": ans.outcome,
        "abstain_reason": ans.abstain_reason,
        "citations": citations_list,
        "model": ans.model,
        "usage": {
            "input_tokens": int(ans.usage.input_tokens),
            "output_tokens": int(ans.usage.output_tokens),
        },
        "latency_ms": int(ans.latency_ms),
    }

    if include_retrieved:
        d["retrieved"] = [retrieved_to_dict(rc, include_text=True) for rc in ans.retrieved]

    return d


def index_report_to_dict(report: IndexReport) -> dict[str, Any]:
    """Serialize an IndexReport to a plain dictionary."""
    return {
        "indexed": list(report.indexed),
        "skipped": list(report.skipped),
        "failed": [{"source": str(src), "reason": str(reason)} for src, reason in report.failed],
        "chunks": int(report.chunks),
        "seconds": round(float(report.seconds), 3),
    }
