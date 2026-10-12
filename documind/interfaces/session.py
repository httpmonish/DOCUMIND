"""documind/interfaces/session.py
Multi-user session manager providing tenant-isolated document workspaces.
Guarantees physical and logical isolation between public demo visitors.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request, status

from documind.core.config import Settings
from documind.core.pipeline import DocuMind
from documind.core.types import LLM, Embedder
from documind.core.vector_store import ChromaStore

logger = logging.getLogger(__name__)

SESSION_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{16,64}$")


def validate_session_id(raw_id: str | None) -> str:
    """Validate that session ID matches strict opaque token format.
    Rejects path traversal or malformed strings.
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


def get_session_id_from_request(request: Request) -> str:
    """Extract and validate X-Session-ID header from incoming request."""
    raw = request.headers.get("X-Session-ID")
    return validate_session_id(raw)


@dataclass
class SessionEntry:
    session_id: str
    engine: DocuMind
    workspace_dir: Path
    last_accessed: float
    lock: threading.Lock


class SessionManager:
    """Manages isolated session engines, storage paths, and lifecycle cleanup."""

    def __init__(
        self,
        base_dir: Path,
        shared_embedder: Embedder,
        shared_llm: LLM | None,
        settings: Settings,
        ttl_seconds: int = 7200,  # 2 hours
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.shared_embedder = shared_embedder
        self.shared_llm = shared_llm
        self.settings = settings
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, SessionEntry] = {}
        self._lock = threading.Lock()

        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_session_dir(self, session_id: str) -> Path:
        """Derive safe path for session workspace, preventing traversal."""
        clean_id = validate_session_id(session_id)
        session_path = (self.base_dir / clean_id).resolve()
        if not session_path.is_relative_to(self.base_dir):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid session path.",
            )
        return session_path

    def get_uploads_dir(self, session_id: str) -> Path:
        """Retrieve uploads directory for specific session."""
        session_dir = self.get_session_dir(session_id)
        uploads_dir = session_dir / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        return uploads_dir

    def get_engine(self, session_id: str) -> tuple[DocuMind, threading.Lock]:
        """Retrieve or create an isolated DocuMind engine for the given session.
        Reuses shared in-memory embedder and LLM to prevent memory overhead,
        while strictly partitioning the ChromaStore and document directories.
        """
        clean_id = validate_session_id(session_id)
        now = time.time()

        with self._lock:
            entry = self._sessions.get(clean_id)
            if entry is not None:
                entry.last_accessed = now
                return entry.engine, entry.lock

            # Initialize new isolated session workspace
            session_dir = self.get_session_dir(clean_id)
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
            )

            engine = DocuMind(
                settings=session_settings,
                embedder=self.shared_embedder,
                store=store,
                llm=self.shared_llm,
            )

            entry = SessionEntry(
                session_id=clean_id,
                engine=engine,
                workspace_dir=session_dir,
                last_accessed=now,
                lock=threading.Lock(),
            )
            self._sessions[clean_id] = entry
            return entry.engine, entry.lock

    def delete_session(self, session_id: str) -> bool:
        """Purge all data and memory references for a specific session."""
        clean_id = validate_session_id(session_id)
        session_dir = self.get_session_dir(clean_id)

        with self._lock:
            self._sessions.pop(clean_id, None)

        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)
            return True
        return False

    def cleanup_expired(self) -> int:
        """Sweep and purge sessions exceeding TTL."""
        now = time.time()
        expired: list[str] = []

        with self._lock:
            for sid, entry in self._sessions.items():
                if now - entry.last_accessed > self.ttl_seconds:
                    expired.append(sid)

            for sid in expired:
                del self._sessions[sid]

        count = len(expired)
        for sid in expired:
            session_dir = self.base_dir / sid
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)

        return count

    def count_active_sessions(self) -> int:
        """Return number of cached active sessions."""
        with self._lock:
            return len(self._sessions)
