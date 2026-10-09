#!/usr/bin/env python3
"""scripts/cost_sum.py -- Summarize cumulative spend from query logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from documind.core.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Sum query log costs.")
    parser.add_argument("--log", type=Path, default=None, help="Path to queries.jsonl")
    args = parser.parse_args()

    if args.log:
        log_path = args.log
    else:
        settings = load_settings()
        log_path = settings.home / "logs" / "queries.jsonl"

    if not log_path.exists():
        print(f"Log file {log_path} does not exist.")
        return

    count = 0
    null_cost_count = 0
    total_cost = 0.0

    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        count += 1
        record = json.loads(line)
        c = record.get("cost_usd")
        if c is None:
            null_cost_count += 1
        else:
            total_cost += float(c)

    print(f"Total queries:      {count}")
    print(f"Queries with cost:  {count - null_cost_count}")
    print(f"Queries null cost:  {null_cost_count}")
    print(f"Cumulative spend:   ${total_cost:.6f} (₹{total_cost * 86.5:.2f})")


if __name__ == "__main__":
    main()
