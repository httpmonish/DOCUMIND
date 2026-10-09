"""documind/core/logging_utils.py
JSONL query logger with rotating file handler and schema normalization.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import numpy as np


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class QueryLogger:
    """Writes single-line JSON records to a rotating log file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        logger_name = f"documind.query_logger.{self.path}"
        self._logger = logging.getLogger(logger_name)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

        # Prevent duplicate handlers on re-initialization
        if not any(
            isinstance(h, RotatingFileHandler)
            and Path(getattr(h, "baseFilename", "")).resolve() == self.path
            for h in self._logger.handlers
        ):
            handler = RotatingFileHandler(
                self.path,
                maxBytes=5_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

    def write(self, record: dict[str, Any]) -> None:
        """Serialize record to JSON and write to log."""
        line = json.dumps(record, separators=(",", ":"), default=_json_default)
        self._logger.info(line)
