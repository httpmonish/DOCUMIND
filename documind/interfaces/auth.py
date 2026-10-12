"""documind/interfaces/auth.py
Secure multi-user authentication and session management.
Features:
- Email + password (minimum 10 chars)
- Password hashing with hashlib.scrypt (per-user salt, constant-time compare)
- Session issuance with HttpOnly, SameSite=Lax cookies and CSRF tokens
- Tenant workspace mapping to session_manager
- Guest document migration on account login/registration
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Request, Response

from documind.interfaces.session import SessionManager

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
AUTH_COOKIE_NAME = "documind_auth_session"
DEFAULT_SESSION_TTL_S = 7 * 86400  # 7 days


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class User:
    id: str
    email: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "created_at": self.created_at,
        }


class AuthManager:
    """Manages user registration, credential verification, sessions, and workspaces."""

    def __init__(self, db_path: Path, session_ttl_s: int = DEFAULT_SESSION_TTL_S) -> None:
        self.db_path = Path(db_path).resolve()
        self.session_ttl_s = session_ttl_s
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
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE COLLATE NOCASE NOT NULL,
                    salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)"
            )
            conn.commit()

    @staticmethod
    def hash_password(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            maxmem=32 * 1024 * 1024,
        )

    def register(self, email: str, password: str) -> tuple[User, str, str]:
        """Register a new user account.
        Enforces minimum 10 characters password and email format.
        """
        clean_email = email.strip().lower()
        if not clean_email or not EMAIL_REGEX.match(clean_email):
            raise AuthError("Invalid email address.", status_code=400)

        if len(password) < 10:
            raise AuthError("Password must be at least 10 characters long.", status_code=400)

        salt = os.urandom(16)
        pw_hash = self.hash_password(password, salt)
        user_id = "usr_" + uuid.uuid4().hex[:16]
        now = time.time()

        with self._lock, self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users (id, email, salt, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, clean_email, salt, pw_hash, now),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # Generic error to prevent account enumeration
                raise AuthError("Email already registered or invalid.", status_code=400) from None

        user = User(id=user_id, email=clean_email, created_at=now)
        session_token, csrf_token = self._create_session(user_id)
        return user, session_token, csrf_token

    def login(self, email: str, password: str) -> tuple[User, str, str]:
        """Verify user credentials and issue session.
        Uses constant-time comparison and generic error messages.
        """
        clean_email = email.strip().lower()
        if not clean_email:
            raise AuthError("Invalid email or password.", status_code=401)

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT id, email, salt, password_hash, created_at FROM users WHERE email = ?",
                (clean_email,),
            ).fetchone()

        if not row:
            # Perform dummy scrypt to mitigate timing attacks
            self.hash_password(password, b"1234567890123456")
            raise AuthError("Invalid email or password.", status_code=401)

        expected_hash = bytes(row["password_hash"])
        salt = bytes(row["salt"])
        actual_hash = self.hash_password(password, salt)

        if not hmac.compare_digest(expected_hash, actual_hash):
            raise AuthError("Invalid email or password.", status_code=401)

        user = User(id=row["id"], email=row["email"], created_at=row["created_at"])
        session_token, csrf_token = self._create_session(user.id)
        return user, session_token, csrf_token

    def _create_session(self, user_id: str) -> tuple[str, str]:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + self.session_ttl_s

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions
                (session_token, user_id, csrf_token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_token, user_id, csrf_token, now, expires_at),
            )
            conn.commit()

        return session_token, csrf_token

    def get_user_by_session(self, session_token: str | None) -> tuple[User, str] | None:
        """Validate auth session token and return (User, csrf_token) if valid."""
        if not session_token or not isinstance(session_token, str):
            return None

        clean_token = session_token.strip()
        now = time.time()

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT s.csrf_token, s.expires_at, u.id, u.email, u.created_at
                FROM auth_sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_token = ? AND s.expires_at > ?
                """,
                (clean_token, now),
            ).fetchone()

        if not row:
            return None

        user = User(id=row["id"], email=row["email"], created_at=row["created_at"])
        return user, row["csrf_token"]

    def logout(self, session_token: str | None) -> None:
        """Invalidate auth session."""
        if not session_token:
            return
        clean_token = session_token.strip()
        with self._lock, self._get_connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE session_token = ?", (clean_token,))
            conn.commit()

    @staticmethod
    def get_user_workspace_hash(user_id: str) -> str:
        """Deterministically calculate 64-char hex hash for user's tenant workspace."""
        return hashlib.sha256(f"user_workspace_{user_id}".encode()).hexdigest()

    def claim_guest_workspace(
        self,
        guest_token_or_hash: str,
        user_id: str,
        session_mgr: SessionManager,
    ) -> bool:
        """Move guest session documents and storage into user's workspace."""
        if not guest_token_or_hash:
            return False

        try:
            # Check if token needs hashing
            is_hex_64 = len(guest_token_or_hash) == 64 and all(
                c in "0123456789abcdef" for c in guest_token_or_hash
            )
            if is_hex_64:
                guest_hash = guest_token_or_hash
            else:
                guest_hash = hashlib.sha256(guest_token_or_hash.strip().encode()).hexdigest()

            guest_dir = session_mgr.base_dir / guest_hash
            if not guest_dir.exists() or not guest_dir.is_dir():
                return False

            user_hash = self.get_user_workspace_hash(user_id)
            user_dir = session_mgr.base_dir / user_hash
            user_dir.mkdir(parents=True, exist_ok=True)

            # Copy uploads from guest to user workspace
            guest_uploads = guest_dir / "uploads"
            user_uploads = user_dir / "uploads"
            user_uploads.mkdir(parents=True, exist_ok=True)

            # Ensure user workspace is registered in session manager
            session_mgr.register_session(user_hash, ip_hash="auth_user")
            user_engine, user_lock = session_mgr.get_engine(user_hash)

            if guest_uploads.exists() and guest_uploads.is_dir():
                for item in guest_uploads.glob("*"):
                    if item.is_file():
                        dest_file = user_uploads / item.name
                        shutil.copy2(item, dest_file)
                        parts = item.name.split("_", 1)
                        doc_source = parts[1] if len(parts) > 1 else item.name
                        try:
                            content = dest_file.read_text(encoding="utf-8")
                            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                            with user_lock:
                                user_engine.index_text(content, doc_source, sha)
                        except Exception as e:
                            logger.warning("Error migrating doc %s: %s", item.name, e)

            return True
        except Exception as e:
            logger.error("Failed to migrate guest session: %s", e)
            return False


def set_auth_cookie(response: Response, session_token: str, request: Request | None = None) -> None:
    is_https = False
    if request:
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto") == "https"
        )
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=session_token,
        max_age=DEFAULT_SESSION_TTL_S,
        httponly=True,
        samesite="lax",
        secure=is_https,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
        samesite="lax",
    )
