"""documind/interfaces/session.py
Multi-user session manager providing tenant-isolated document workspaces.
Guarantees physical and logical isolation between public demo visitors.
Backs session state with SQLite registry, enforcing server-issued tokens,
TTL expiration, and document/byte limits.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import LLM, Embedder
from documind.core.vector_store import ChromaStore

logger = logging.getLogger(__name__)

SESSION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{16,64}$")


def validate_session_id_format(raw_id: str | None) -> str:
    """Validate that session ID matches strict opaque token format.
    Rejects missing, path traversal, or malformed strings with 400 Bad Request.
    """
    if not raw_id or not isinstance(raw_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required X-Session-ID header.",
        )
    clean_id = raw_id.strip()
    if not SESSION_ID_REGEX.match(clean_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid session ID format. "
                "Must be 16-64 alphanumeric characters, underscores, or hyphens."
            ),
        )
    return clean_id


# Alias for backward compatibility
validate_session_id = validate_session_id_format


def get_session_id_from_request(request: Request) -> str:
    """Extract and validate session token from header or cookie."""
    raw = request.headers.get("X-Session-ID")
    if not raw:
        raw = request.cookies.get("documind_session")
    return validate_session_id_format(raw)


def token_to_hash(token: str) -> str:
    """Compute SHA-256 hex digest of session token for safe storage and directory naming."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_session_identifier(identifier: str) -> str:
    """Normalize session token or session hash to canonical 64-char hex hash."""
    clean = validate_session_id_format(identifier)
    if len(clean) == 64 and all(c in "0123456789abcdef" for c in clean):
        return clean
    return token_to_hash(clean)


@dataclass
class SessionEntry:
    session_hash: str
    engine: DocuMind
    workspace_dir: Path
    last_accessed: float
    lock: threading.Lock


class SessionManager:
    """Manages isolated session engines, storage paths, SQLite registry, and limits."""

    def __init__(
        self,
        base_dir: Path,
        shared_embedder: Embedder,
        shared_llm: LLM | None,
        settings: Settings,
        ttl_seconds: int = 7200,  # 2 hours
        enforce_registered: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.shared_embedder = shared_embedder
        self.shared_llm = shared_llm
        self.settings = settings
        self.ttl_seconds = ttl_seconds
        self.enforce_registered = enforce_registered
        self._sessions: dict[str, SessionEntry] = {}
        self._lock = threading.Lock()

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "sessions.db"
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_hash TEXT PRIMARY KEY,
                    token TEXT,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    ip_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    doc_count INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.commit()

    def create_session(self, ip_hash: str) -> tuple[str, float]:
        """Issue a fresh cryptographically random session token registered in SQLite."""
        token = secrets.token_urlsafe(32)
        s_hash = token_to_hash(token)
        now = time.time()
        expires_at = now + self.ttl_seconds

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_hash, token, created_at, last_accessed,
                    expires_at, ip_hash, status, doc_count, total_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, 0)
                """,
                (s_hash, token, now, now, expires_at, ip_hash),
            )
            conn.commit()

        session_dir = self.base_dir / s_hash
        session_dir.mkdir(parents=True, exist_ok=True)
        return token, expires_at

    def register_session(self, token: str, ip_hash: str = "test") -> str:
        """Explicitly register a specific session token (useful for test fixtures)."""
        clean_token = validate_session_id_format(token)
        s_hash = token_to_hash(clean_token)
        now = time.time()
        expires_at = now + self.ttl_seconds

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_hash, token, created_at, last_accessed,
                    expires_at, ip_hash, status, doc_count, total_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', 0, 0)
                ON CONFLICT(session_hash) DO UPDATE SET
                    last_accessed = excluded.last_accessed,
                    expires_at = excluded.expires_at,
                    status = 'active'
                """,
                (s_hash, clean_token, now, now, expires_at, ip_hash),
            )
            conn.commit()

        session_dir = self.base_dir / s_hash
        session_dir.mkdir(parents=True, exist_ok=True)
        return s_hash

    def validate_token(self, raw_token: str | None) -> str:
        """Validate token format and confirm active registration in SQLite.
        Returns the safe session_hash if valid.
        Raises 400 for format errors, 401 for unknown or expired tokens.
        """
        token = validate_session_id_format(raw_token)
        s_hash = token_to_hash(token)
        now = time.time()

        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT status, expires_at FROM sessions WHERE session_hash = ?",
                (s_hash,),
            )
            row = cur.fetchone()

            if row is None:
                if not self.enforce_registered:
                    # In permissive mode (e.g. initial dev), auto-register
                    return self.register_session(token)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session token invalid or not found. Please create a new session.",
                )

            if row["status"] != "active":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session has been revoked. Please create a new session.",
                )

            if now > row["expires_at"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session has expired. Please create a new session.",
                )

            # Update last accessed time
            conn.execute(
                "UPDATE sessions SET last_accessed = ? WHERE session_hash = ?",
                (now, s_hash),
            )
            conn.commit()

        return s_hash

    def get_session_dir(self, session_identifier: str) -> Path:
        """Derive safe path for session workspace keyed by session hash."""
        s_hash = normalize_session_identifier(session_identifier)
        session_path = (self.base_dir / s_hash).resolve()
        if not session_path.is_relative_to(self.base_dir):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid session path.",
            )
        return session_path

    def get_uploads_dir(self, session_identifier: str) -> Path:
        """Retrieve uploads directory for specific session."""
        session_dir = self.get_session_dir(session_identifier)
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        return uploads_dir

    def get_session_info(self, session_identifier: str) -> dict[str, Any] | None:
        """Retrieve metadata for session."""
        s_hash = normalize_session_identifier(session_identifier)
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM sessions WHERE session_hash = ?",
                (s_hash,),
            )
            row = cur.fetchone()
            if row:
                return dict(row)
        return None

    def record_upload(
        self,
        session_identifier: str,
        byte_count: int,
        max_docs: int = 5,
        max_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        """Validate session upload limits (max 5 files, 20 MB total) and record usage."""
        s_hash = normalize_session_identifier(session_identifier)
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT doc_count, total_bytes FROM sessions WHERE session_hash = ?",
                (s_hash,),
            )
            row = cur.fetchone()
            if row:
                current_docs = row["doc_count"]
                current_bytes = row["total_bytes"]

                if current_docs >= max_docs:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Demo session limit reached (maximum {max_docs} documents). "
                            "Delete an existing document to upload another."
                        ),
                    )

                if current_bytes + byte_count > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Demo session storage limit reached (maximum 20 MB total). "
                            "Delete existing documents to free storage."
                        ),
                    )

                conn.execute(
                    """
                    UPDATE sessions
                    SET doc_count = doc_count + 1,
                        total_bytes = total_bytes + ?
                    WHERE session_hash = ?
                    """,
                    (byte_count, s_hash),
                )
                conn.commit()

    def record_delete(self, session_identifier: str, byte_count: int = 0) -> None:
        """Decrement session document and byte count."""
        s_hash = normalize_session_identifier(session_identifier)
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET doc_count = MAX(0, doc_count - 1),
                    total_bytes = MAX(0, total_bytes - ?)
                WHERE session_hash = ?
                """,
                (byte_count, s_hash),
            )
            conn.commit()

    def get_engine(self, session_identifier: str) -> tuple[DocuMind, threading.Lock]:
        """Retrieve or initialize isolated DocuMind engine for the given session.
        Accepts either session_hash or raw session token.
        """
        s_hash = normalize_session_identifier(session_identifier)
        now = time.time()

        with self._lock:
            entry = self._sessions.get(s_hash)
            if entry is not None:
                entry.last_accessed = now
                return entry.engine, entry.lock

            # Initialize new isolated session workspace
            session_dir = self.base_dir / s_hash
            session_dir.mkdir(parents=True, exist_ok=True)
            chroma_dir = session_dir / "chroma"
            uploads_dir = session_dir / "uploads"
            chroma_dir.mkdir(parents=True, exist_ok=True)
            uploads_dir.mkdir(parents=True, exist_ok=True)

            store = ChromaStore(
                path=chroma_dir,
                model_slug=self.shared_embedder.model_id,
                dim=self.shared_embedder.dim,
            )

            # Derive session settings with home set to session_dir
            session_settings = Settings(
                home=session_dir,
                embed_model=self.settings.embed_model,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.overlap,
                top_k=self.settings.top_k,
                max_file_mb=self.settings.max_file_mb,
                max_pages=self.settings.max_pages,
                model=self.settings.model,
                min_score=self.settings.min_score,
                max_tokens=self.settings.max_tokens,
                llm_timeout_s=self.settings.llm_timeout_s,
                llm_retries=self.settings.llm_retries,
                log_questions=self.settings.log_questions,
                api_key=self.settings.api_key,
                env=self.settings.env,
                rate_limit_per_min=self.settings.rate_limit_per_min,
                max_upload_mb=self.settings.max_upload_mb,
                allow_debug=self.settings.allow_debug,
                llm_provider=self.settings.llm_provider,
                openai_base_url=self.settings.openai_base_url,
                openai_api_key=self.settings.openai_api_key,
            )

            engine = DocuMind(
                settings=session_settings,
                embedder=self.shared_embedder,
                store=store,
                llm=self.shared_llm,
            )

            entry = SessionEntry(
                session_hash=s_hash,
                engine=engine,
                workspace_dir=session_dir,
                last_accessed=now,
                lock=threading.Lock(),
            )
            self._sessions[s_hash] = entry
            return entry.engine, entry.lock

    def delete_session(self, session_identifier: str) -> bool:
        """Purge all data and memory references for a specific session."""
        s_hash = normalize_session_identifier(session_identifier)
        session_dir = self.base_dir / s_hash

        with self._lock:
            self._sessions.pop(s_hash, None)
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE sessions SET status = 'revoked' WHERE session_hash = ?",
                    (s_hash,),
                )
                conn.commit()

        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
            return True
        return False

    def cleanup_expired(self) -> int:
        """Sweep and purge sessions exceeding TTL."""
        now = time.time()
        expired: list[str] = []

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT session_hash FROM sessions WHERE status = 'active' AND expires_at < ?",
                    (now,),
                )
                expired = [row["session_hash"] for row in cur.fetchall()]

                if expired:
                    conn.executemany(
                        "UPDATE sessions SET status = 'expired' WHERE session_hash = ?",
                        [(h,) for h in expired],
                    )
                    conn.commit()

            for h in expired:
                self._sessions.pop(h, None)

        for h in expired:
            session_dir = self.base_dir / h
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)

        return len(expired)

    def count_active_sessions(self) -> int:
        """Return number of active sessions in SQLite."""
        now = time.time()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) as cnt FROM sessions WHERE status = 'active' AND expires_at > ?",
                (now,),
            )
            row = cur.fetchone()
            return row["cnt"] if row else 0
