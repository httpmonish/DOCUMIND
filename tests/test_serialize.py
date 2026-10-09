"""tests/test_serialize.py -- contract for documind/core/serialize.py
(one JSON shape shared by CLI, REST and MCP).
"""

from __future__ import annotations

import json

import numpy as np

from documind.core.ingest import IndexReport
from documind.core.serialize import answer_to_dict, index_report_to_dict, retrieved_to_dict
from documind.core.types import Answer, Chunk, Citation, RetrievedChunk, Usage

CHUNK = Chunk("a.md_chunk_0003", "x" * 300, "a.md", 3, "sha")
# numpy scalar on purpose: json.dumps rejects it
HIT = RetrievedChunk(CHUNK, np.float32(0.123456), 2)
ANSWER = Answer(
    "Counter [S1]",
    (Citation("S1", "a.md", 3, "x" * 200, np.float32(0.123456)),),
    "answered",
    "claude-haiku-4-5-20251001",
    Usage(1700, 300),
    1234,
    (HIT,),
    None,
)


def test_answer_dict_is_plain_json_with_a_stable_shape():
    d = answer_to_dict(ANSWER)
    json.dumps(d)  # must not raise
    assert list(d) == [
        "text",
        "outcome",
        "abstain_reason",
        "citations",
        "model",
        "usage",
        "latency_ms",
    ]
    assert d["abstain_reason"] is None and d["usage"] == {
        "input_tokens": 1700,
        "output_tokens": 300,
    }
    assert d["citations"] == [
        {
            "marker": "S1",
            "source": "a.md",
            "chunk_index": 3,
            "snippet": "x" * 200,
            "score": 0.1235,
        }
    ]
    assert "retrieved" not in d  # chunk text is not exposed by default


def test_debug_mode_adds_retrieved_chunks_with_full_text():
    d = answer_to_dict(ANSWER, include_retrieved=True)
    json.dumps(d)
    assert d["retrieved"][0]["text"] == "x" * 300 and d["retrieved"][0]["rank"] == 2
    assert d["retrieved"][0]["score"] == 0.1235


def test_retrieved_dict_has_a_snippet_and_text_only_on_request():
    d = retrieved_to_dict(HIT)
    assert d["snippet"] == "x" * 200 and "text" not in d and d["id"] == "a.md_chunk_0003"
    assert retrieved_to_dict(HIT, include_text=True)["text"] == "x" * 300


def test_index_report_dict():
    r = IndexReport(["a.md"], ["b.md"], [("c.pdf", "unreadable")], 12, 1.23456)
    d = index_report_to_dict(r)
    json.dumps(d)
    assert d == {
        "indexed": ["a.md"],
        "skipped": ["b.md"],
        "failed": [{"source": "c.pdf", "reason": "unreadable"}],
        "chunks": 12,
        "seconds": 1.235,
    }
