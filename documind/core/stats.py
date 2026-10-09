"""documind/core/stats.py
Log aggregation and metrics reporting for DocuMind queries.
Parses queries.jsonl to summarize query volumes, outcomes, latency, and costs.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from documind.core.eval_metrics import percentile


def parse_iso_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp, normalizing to UTC."""
    # Replace Z with +00:00 for older Python if needed
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def aggregate_query_logs(
    log_path: Path,
    *,
    days: float | int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate statistics from queries.jsonl log file."""
    empty_result: dict[str, Any] = {
        "query_count": 0,
        "outcomes": {},
        "abstain_reasons": {},
        "latency_p50_ms": None,
        "latency_p95_ms": None,
        "total_cost_usd": 0.0,
    }

    if not log_path.exists():
        return empty_result

    cutoff: datetime | None = None
    if days is not None:
        current_time = now or datetime.now(timezone.utc)
        cutoff = current_time - timedelta(days=float(days))

    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            rec = None
        if not isinstance(rec, dict):
            continue

        if cutoff is not None and "ts" in rec:
            try:
                rec_dt = parse_iso_ts(rec["ts"])
                if rec_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                # Skip date filtering on unparseable timestamps
                rec_dt = None

        records.append(rec)

    if not records:
        return empty_result

    outcomes_counter: Counter[str] = Counter()
    reasons_counter: Counter[str] = Counter()
    latencies: list[float] = []
    total_cost = 0.0

    for r in records:
        outcome = r.get("outcome")
        if outcome:
            outcomes_counter[outcome] += 1

        reason = r.get("abstain_reason")
        if reason:
            reasons_counter[reason] += 1

        lat = r.get("total_ms")
        if lat is not None:
            latencies.append(float(lat))

        cost = r.get("cost_usd")
        if cost is not None:
            total_cost += float(cost)

    p50 = percentile(latencies, 50.0) if latencies else None
    p95 = percentile(latencies, 95.0) if latencies else None

    return {
        "query_count": len(records),
        "outcomes": dict(outcomes_counter),
        "abstain_reasons": dict(reasons_counter),
        "latency_p50_ms": round(p50, 1) if p50 is not None else None,
        "latency_p95_ms": round(p95, 1) if p95 is not None else None,
        "total_cost_usd": round(total_cost, 6),
    }
