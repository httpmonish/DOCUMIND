"""documind/interfaces/spend.py
Daily spend tracking and fail-closed budget control for the public demo.
Calculates token economics at Claude Haiku 4.5 published rates ($1.00/M in, $5.00/M out).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Claude Haiku 4.5 pricing
INPUT_COST_PER_M: float = 1.00
OUTPUT_COST_PER_M: float = 5.00

DEFAULT_GLOBAL_DAILY_CAP_USD: float = 2.00
DEFAULT_IP_DAILY_CAP_USD: float = 0.25


def calculate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for token consumption."""
    in_cost = (input_tokens * INPUT_COST_PER_M) / 1_000_000.0
    out_cost = (output_tokens * OUTPUT_COST_PER_M) / 1_000_000.0
    return round(in_cost + out_cost, 6)


def estimate_generation_cost(
    prompt_tokens: int,
    max_output_tokens: int = 600,
) -> float:
    """Estimate conservative upper bound for a query before generation."""
    return calculate_cost_usd(prompt_tokens, max_output_tokens)


class SpendLedger:
    """Thread-safe SQLite-backed daily spend ledger.
    Tracks global and per-IP daily spend against configured spending caps.
    """

    def __init__(
        self,
        db_path: Path,
        global_daily_cap_usd: float = DEFAULT_GLOBAL_DAILY_CAP_USD,
        ip_daily_cap_usd: float = DEFAULT_IP_DAILY_CAP_USD,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.global_daily_cap_usd = global_daily_cap_usd
        self.ip_daily_cap_usd = ip_daily_cap_usd
        self._lock = threading.Lock()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_spend (
                    date_utc TEXT NOT NULL,
                    entity_key TEXT NOT NULL,
                    spent_usd REAL NOT NULL DEFAULT 0.0,
                    reserved_usd REAL NOT NULL DEFAULT 0.0,
                    PRIMARY KEY (date_utc, entity_key)
                )
                """
            )
            conn.commit()

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def can_spend(self, ip_hash: str, estimated_usd: float) -> tuple[bool, str | None]:
        """Verify whether an estimated cost would breach global or IP caps."""
        today = self._today()
        with self._lock, self._get_connection() as conn:
            # Check global
            cur = conn.execute(
                """
                SELECT spent_usd, reserved_usd
                FROM daily_spend
                WHERE date_utc = ? AND entity_key = 'global'
                """,
                (today,),
            )
            row = cur.fetchone()
            g_spent = row["spent_usd"] if row else 0.0
            g_reserved = row["reserved_usd"] if row else 0.0

            if (g_spent + g_reserved + estimated_usd) > self.global_daily_cap_usd:
                logger.warning(
                    "Global daily cap hit: spent=$%.4f, reserved=$%.4f, est=$%.4f, cap=$%.2f",
                    g_spent,
                    g_reserved,
                    estimated_usd,
                    self.global_daily_cap_usd,
                )
                return False, "global_daily_cap_reached"

            # Check IP
            cur = conn.execute(
                """
                SELECT spent_usd, reserved_usd
                FROM daily_spend
                WHERE date_utc = ? AND entity_key = ?
                """,
                (today, f"ip:{ip_hash}"),
            )
            row = cur.fetchone()
            ip_spent = row["spent_usd"] if row else 0.0
            ip_reserved = row["reserved_usd"] if row else 0.0

            if (ip_spent + ip_reserved + estimated_usd) > self.ip_daily_cap_usd:
                logger.warning(
                    "IP daily cap hit for %s: spent=$%.4f, reserved=$%.4f, est=$%.4f, cap=$%.2f",
                    ip_hash,
                    ip_spent,
                    ip_reserved,
                    estimated_usd,
                    self.ip_daily_cap_usd,
                )
                return False, "ip_daily_cap_reached"

        return True, None

    def reserve(self, ip_hash: str, session_hash: str, estimated_usd: float) -> None:
        """Reserve estimated funds before initiating LLM call."""
        today = self._today()
        keys = ["global", f"ip:{ip_hash}", f"session:{session_hash}"]

        with self._lock, self._get_connection() as conn:
            for key in keys:
                conn.execute(
                    """
                    INSERT INTO daily_spend (date_utc, entity_key, spent_usd, reserved_usd)
                    VALUES (?, ?, 0.0, ?)
                    ON CONFLICT(date_utc, entity_key) DO UPDATE SET
                        reserved_usd = reserved_usd + excluded.reserved_usd
                    """,
                    (today, key, estimated_usd),
                )
            conn.commit()

    def settle(
        self,
        ip_hash: str,
        session_hash: str,
        reserved_usd: float,
        actual_usd: float,
    ) -> None:
        """Settle reservation with actual generation cost."""
        today = self._today()
        keys = ["global", f"ip:{ip_hash}", f"session:{session_hash}"]

        with self._lock, self._get_connection() as conn:
            for key in keys:
                conn.execute(
                    """
                    INSERT INTO daily_spend (date_utc, entity_key, spent_usd, reserved_usd)
                    VALUES (?, ?, ?, 0.0)
                    ON CONFLICT(date_utc, entity_key) DO UPDATE SET
                        spent_usd = spent_usd + excluded.spent_usd,
                        reserved_usd = MAX(0.0, reserved_usd - ?)
                    """,
                    (today, key, actual_usd, reserved_usd),
                )
            conn.commit()

    def release(self, ip_hash: str, session_hash: str, reserved_usd: float) -> None:
        """Release reservation without incurring cost (e.g. on error or abstention)."""
        today = self._today()
        keys = ["global", f"ip:{ip_hash}", f"session:{session_hash}"]

        with self._lock, self._get_connection() as conn:
            for key in keys:
                conn.execute(
                    """
                    UPDATE daily_spend
                    SET reserved_usd = MAX(0.0, reserved_usd - ?)
                    WHERE date_utc = ? AND entity_key = ?
                    """,
                    (reserved_usd, today, key),
                )
            conn.commit()

    def get_summary(self, ip_hash: str | None = None) -> dict[str, Any]:
        """Retrieve daily usage figures."""
        today = self._today()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT spent_usd, reserved_usd
                FROM daily_spend
                WHERE date_utc = ? AND entity_key = 'global'
                """,
                (today,),
            )
            g_row = cur.fetchone()
            g_spent = g_row["spent_usd"] if g_row else 0.0

            ip_spent = 0.0
            if ip_hash:
                cur = conn.execute(
                    """
                    SELECT spent_usd, reserved_usd
                    FROM daily_spend
                    WHERE date_utc = ? AND entity_key = ?
                    """,
                    (today, f"ip:{ip_hash}"),
                )
                ip_row = cur.fetchone()
                ip_spent = ip_row["spent_usd"] if ip_row else 0.0

        return {
            "date_utc": today,
            "global_spent_usd": round(g_spent, 4),
            "global_cap_usd": self.global_daily_cap_usd,
            "ip_spent_usd": round(ip_spent, 4),
            "ip_cap_usd": self.ip_daily_cap_usd,
        }
