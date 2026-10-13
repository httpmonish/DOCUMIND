"""documind/core/chat.py
Multi-turn conversation and message history storage backed by SQLite.
Persists chat trajectories per session hash, maintaining context windows.
"""

from __future__ import annotations

import contextlib
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
    """Manages conversations and messages isolated by session hash and user ownership."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path).resolve()
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    session_hash TEXT NOT NULL,
                    owner_id TEXT,
                    document_id TEXT,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_message_at REAL,
                    archived_at REAL,
                    deleted_at REAL
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
                    updated_at REAL,
                    status TEXT DEFAULT 'completed',
                    citations_json TEXT,
                    retrieved_json TEXT,
                    usage_json TEXT,
                    metadata_json TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
                """
            )

            # Idempotently ensure new columns exist for existing databases
            for table, col, col_type in [
                ("conversations", "owner_id", "TEXT"),
                ("conversations", "document_id", "TEXT"),
                ("conversations", "last_message_at", "REAL"),
                ("conversations", "archived_at", "REAL"),
                ("conversations", "deleted_at", "REAL"),
                ("messages", "updated_at", "REAL"),
                ("messages", "status", "TEXT DEFAULT 'completed'"),
                ("messages", "metadata_json", "TEXT"),
            ]:
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type};")

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_hash)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations(owner_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at)"
            )
            conn.commit()

    def create_conversation(
        self,
        session_hash: str,
        title: str = "New Conversation",
        owner_id: str | None = None,
        document_id: str | None = None,
    ) -> str:
        """Create a new conversation thread for the given session or owner."""
        conv_id = str(uuid.uuid4())
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO conversations
                (id, session_hash, owner_id, document_id, title,
                 created_at, updated_at, last_message_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (conv_id, session_hash, owner_id, document_id, title, now, now, now),
            )
            conn.commit()
        return conv_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Retrieve conversation metadata by ID."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.id, c.session_hash, c.owner_id, c.document_id, c.title,
                       c.created_at, c.updated_at, c.last_message_at, c.archived_at,
                       c.deleted_at, COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.id = ? AND c.deleted_at IS NULL
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
                """
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (title, now, conversation_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        """Alias for update_conversation_title."""
        return self.update_conversation_title(conversation_id, title)

    def archive_conversation(self, conversation_id: str) -> bool:
        """Archive a conversation thread."""
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "UPDATE conversations SET archived_at = ?, updated_at = ? WHERE id = ?",
                (now, now, conversation_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_conversations(
        self,
        session_hash: str,
        owner_id: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """List all conversation threads for a session or owner, ordered by recent activity."""
        archived_filter = 1 if include_archived else 0
        with self._lock, self._get_connection() as conn:
            if owner_id:
                cur = conn.execute(
                    """
                    SELECT c.id, c.session_hash, c.owner_id, c.document_id, c.title,
                           c.created_at, c.updated_at, c.last_message_at, c.archived_at,
                           COUNT(m.id) as message_count
                    FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    WHERE (c.owner_id = ? OR c.session_hash = ?)
                      AND c.deleted_at IS NULL
                      AND (? = 1 OR c.archived_at IS NULL)
                    GROUP BY c.id
                    ORDER BY COALESCE(c.last_message_at, c.updated_at) DESC
                    """,
                    (owner_id, session_hash, archived_filter),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT c.id, c.session_hash, c.owner_id, c.document_id, c.title,
                           c.created_at, c.updated_at, c.last_message_at, c.archived_at,
                           COUNT(m.id) as message_count
                    FROM conversations c
                    LEFT JOIN messages m ON c.id = m.conversation_id
                    WHERE c.session_hash = ?
                      AND c.deleted_at IS NULL
                      AND (? = 1 OR c.archived_at IS NULL)
                    GROUP BY c.id
                    ORDER BY COALESCE(c.last_message_at, c.updated_at) DESC
                    """,
                    (session_hash, archived_filter),
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
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a turn (user or assistant) to the conversation thread."""
        msg_id = str(uuid.uuid4())
        now = time.time()
        c_json = json.dumps(citations) if citations else None
        r_json = json.dumps(retrieved) if retrieved else None
        u_json = json.dumps(usage) if usage else None
        m_json = json.dumps(metadata) if metadata else None

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, created_at, updated_at,
                    status, citations_json, retrieved_json, usage_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    conversation_id,
                    role,
                    content,
                    now,
                    now,
                    status,
                    c_json,
                    r_json,
                    u_json,
                    m_json,
                ),
            )
            conn.execute(
                """
                UPDATE conversations
                SET updated_at = ?, last_message_at = ?
                WHERE id = ?
                """,
                (now, now, conversation_id),
            )
            conn.commit()
        return msg_id

    def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve messages for a conversation in chronological order."""
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT id, role, content, created_at, updated_at, status,
                       citations_json, retrieved_json, usage_json, metadata_json
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
                    "conversation_id": conversation_id,
                    "role": row["role"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"] or row["created_at"],
                    "status": row["status"] or "completed",
                    "citations": json.loads(row["citations_json"]) if row["citations_json"] else [],
                    "retrieved": json.loads(row["retrieved_json"]) if row["retrieved_json"] else [],
                    "usage": json.loads(row["usage_json"]) if row["usage_json"] else None,
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
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
        """Delete conversation and all its messages."""
        now = time.time()
        with self._lock, self._get_connection() as conn:
            # Soft delete in conversations table to preserve auditability while
            # removing from user view
            cur = conn.execute(
                "UPDATE conversations SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, conversation_id),
            )
            conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            conn.commit()
            return cur.rowcount > 0

