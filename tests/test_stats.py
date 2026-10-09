"""tests/test_stats.py -- unit tests for query log aggregation and stats calculation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from documind.core.stats import aggregate_query_logs


def test_aggregate_empty_or_missing_log(tmp_path: Path):
    missing = tmp_path / "missing.jsonl"
    s = aggregate_query_logs(missing)
    assert s["query_count"] == 0
    assert s["outcomes"] == {}
    assert s["total_cost_usd"] == 0.0

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    s2 = aggregate_query_logs(empty)
    assert s2["query_count"] == 0


def test_aggregate_with_sample_records(tmp_path: Path):
    log_file = tmp_path / "queries.jsonl"
    records = [
        {
            "ts": "2026-10-09T10:00:00Z",
            "outcome": "answered",
            "abstain_reason": None,
            "total_ms": 100,
            "cost_usd": 0.0032,
        },
        {
            "ts": "2026-10-09T11:00:00Z",
            "outcome": "answered",
            "abstain_reason": None,
            "total_ms": 200,
            "cost_usd": 0.0032,
        },
        {
            "ts": "2026-10-09T12:00:00Z",
            "outcome": "abstained",
            "abstain_reason": "low_score",
            "total_ms": 50,
            "cost_usd": 0.0,
        },
    ]
    log_file.write_text(
        "\n".join(json.dumps(r) for r in records),
        encoding="utf-8",
    )

    s = aggregate_query_logs(log_file)
    assert s["query_count"] == 3
    assert s["outcomes"] == {"answered": 2, "abstained": 1}
    assert s["abstain_reasons"] == {"low_score": 1}
    assert s["latency_p50_ms"] == 100.0
    assert s["total_cost_usd"] == 0.0064


def test_aggregate_days_filter(tmp_path: Path):
    log_file = tmp_path / "queries.jsonl"
    records = [
        {
            "ts": "2026-10-01T10:00:00Z",  # 8 days ago
            "outcome": "answered",
            "total_ms": 150,
            "cost_usd": 0.0032,
        },
        {
            "ts": "2026-10-08T10:00:00Z",  # 1 day ago
            "outcome": "answered",
            "total_ms": 250,
            "cost_usd": 0.0032,
        },
    ]
    log_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    now = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
    s = aggregate_query_logs(log_file, days=2, now=now)
    assert s["query_count"] == 1
    assert s["latency_p50_ms"] == 250.0
