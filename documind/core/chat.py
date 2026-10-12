"""documind/core/chat.py
Multi-turn conversation and message history storage backed by SQLite.
Persists chat trajectories per session hash, maintaining context windows.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChatManager:
    """Manages conversations and messages isolated by session hash."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).resolve()
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
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    session_hash TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    citations_json TEXT,
                    retrieved_json TEXT,
                    usage_json TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at)"
            )
            conn.commit()

    def create_conversation(
        self,
        session_hash: str,
        title: str = "New Conversation",
    ) -> str:
        """Create a new conversation thread for the given session."""
        conv_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversations (id, session_hash, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conv_id, session_hash, title, now, now),
            )
            conn.commit()
        return conv_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Retrieve conversation metadata by ID."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.id, c.session_hash, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (conversation_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """Update conversation title."""
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_conversations(self, session_hash: str) -> list[dict[str, Any]]:
        """List all conversation threads for a session, ordered by recent activity."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.id, c.session_hash, c.title, c.created_at, c.updated_at,
                       COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.session_hash = ?
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                """,
                (session_hash,),
            )
            return [dict(row) for row in cur.fetchall()]

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        retrieved: list[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> str:
        """Add a turn (user or assistant) to the conversation thread."""
        msg_id = str(uuid.uuid4())
        now = time.time()
        c_json = json.dumps(citations) if citations else None
        r_json = json.dumps(retrieved) if retrieved else None
        u_json = json.dumps(usage) if usage else None

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, created_at,
                    citations_json, retrieved_json, usage_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, conversation_id, role, content, now, c_json, r_json, u_json),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            conn.commit()
        return msg_id

    def get_messages(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Retrieve recent messages for a conversation."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, role, content, created_at, citations_json, retrieved_json, usage_json
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
            messages = []
            for row in cur.fetchall():
                item = {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "citations": json.loads(row["citations_json"]) if row["citations_json"] else [],
                    "retrieved": json.loads(row["retrieved_json"]) if row["retrieved_json"] else [],
                    "usage": json.loads(row["usage_json"]) if row["usage_json"] else None,
                }
                messages.append(item)
            return messages

    def get_context_turns(
        self,
        conversation_id: str,
        max_turns: int = 6,
    ) -> list[dict[str, str]]:
        """Retrieve last N dialog turns formatted for condensation prompt."""
        msgs = self.get_messages(conversation_id, limit=max_turns)
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    def delete_conversation(self, conversation_id: str) -> bool:
        """Purge conversation and all its messages."""
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            conn.commit()
            return cur.rowcount > 0
