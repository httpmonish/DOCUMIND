"""documind/interfaces/auth.py
Secure user authentication, session management, identity provider integrations,
and document ownership tracking for DocuMind.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
from documind.migrations.runner import MigrationRunner

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
    display_name: str | None = None
    avatar_url: str | None = None
    account_status: str = "active"
    email_verified: bool = False
    email_verified_at: float | None = None
    last_login_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name or self.email.split("@")[0],
            "avatar_url": self.avatar_url,
            "account_status": self.account_status,
            "email_verified": self.email_verified,
            "email_verified_at": self.email_verified_at,
            "last_login_at": self.last_login_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class AuthManager:
    """Manages user registration, credential verification, sessions, identity linking,
    document ownership, and audit events.
    """

    def __init__(
        self,
        db_path: Path | str,
        database_url: str = "",
        session_ttl_s: int = DEFAULT_SESSION_TTL_S,
    ) -> None:
        self.db_path = Path(db_path).resolve()
        self.database_url = database_url
        self.session_ttl_s = session_ttl_s
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Run database migrations automatically
        runner = MigrationRunner(db_path=self.db_path, database_url=self.database_url)
        runner.run_migrations()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

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

    def log_event(
        self,
        user_id: str | None,
        event_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record operational and security audit events."""
        event_id = "evt_" + uuid.uuid4().hex[:16]
        now = time.time()
        meta_str = json.dumps(metadata or {})
        try:
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO usage_events (id, user_id, event_type, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_id, user_id, event_type, meta_str, now),
                )
                conn.commit()
        except Exception as e:
            logger.warning("Failed to record usage event %s: %s", event_type, e)

    def register(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> tuple[User, str, str]:
        """Register a new user account with normalized email and scrypt password hashing."""
        clean_email = email.strip().lower()
        if not clean_email or not EMAIL_REGEX.match(clean_email):
            raise AuthError("Invalid email address.", status_code=400)

        if len(password) < 10:
            raise AuthError("Password must be at least 10 characters long.", status_code=400)

        salt = os.urandom(16)
        pw_hash = self.hash_password(password, salt)
        user_id = "usr_" + uuid.uuid4().hex[:16]
        now = time.time()
        clean_name = (display_name or clean_email.split("@")[0]).strip()

        with self._lock, self._get_connection() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO users
                    (id, email, display_name, salt, password_hash, account_status,
                     email_verified, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'active', 0, ?, ?)
                    """,
                    (user_id, clean_email, clean_name, salt, pw_hash, now, now),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # Generic message to prevent account enumeration
                self.log_event(
                    None, "registration_duplicate_rejected", {"email_hint": clean_email[:3]}
                )
                raise AuthError("Email already registered or invalid.", status_code=400) from None

        self.log_event(user_id, "user_registered", {"email": clean_email})
        user = User(
            id=user_id,
            email=clean_email,
            display_name=clean_name,
            account_status="active",
            created_at=now,
            updated_at=now,
        )
        session_token, csrf_token = self._create_session(user_id)
        return user, session_token, csrf_token

    def login(
        self,
        email: str,
        password: str,
        ip_hash: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, str, str]:
        """Verify user credentials and issue session."""
        clean_email = email.strip().lower()
        if not clean_email:
            raise AuthError("Invalid email or password.", status_code=401)

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, email, display_name, avatar_url, salt, password_hash,
                       account_status, email_verified, email_verified_at, last_login_at,
                       created_at, updated_at
                FROM users WHERE email = ?
                """,
                (clean_email,),
            ).fetchone()

        if not row:
            # Perform dummy scrypt to mitigate timing attacks
            self.hash_password(password, b"1234567890123456")
            self.log_event(None, "login_failed_nonexistent", {"ip_hash": ip_hash})
            raise AuthError("Invalid email or password.", status_code=401)

        if not row["password_hash"] or not row["salt"]:
            # Account exists via external identity (e.g. Google) without password
            self.hash_password(password, b"1234567890123456")
            self.log_event(row["id"], "login_failed_external_only", {"ip_hash": ip_hash})
            raise AuthError(
                "This account was created with Google sign-in. Please use Google to log in.",
                status_code=401,
            )

        expected_hash = bytes(row["password_hash"])
        salt = bytes(row["salt"])
        actual_hash = self.hash_password(password, salt)

        if not hmac.compare_digest(expected_hash, actual_hash):
            self.log_event(row["id"], "login_failed_bad_password", {"ip_hash": ip_hash})
            raise AuthError("Invalid email or password.", status_code=401)

        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row["id"]))
            conn.commit()

        user = User(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            account_status=row["account_status"],
            email_verified=bool(row["email_verified"]),
            email_verified_at=row["email_verified_at"],
            last_login_at=now,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        self.log_event(user.id, "login_successful", {"ip_hash": ip_hash})
        session_token, csrf_token = self._create_session(
            user.id, ip_hash=ip_hash, user_agent=user_agent
        )
        return user, session_token, csrf_token

    def _create_session(
        self,
        user_id: str,
        ip_hash: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str]:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + self.session_ttl_s

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO user_sessions
                (session_token, user_id, csrf_token, ip_hash, user_agent,
                 created_at, expires_at, revoked)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (session_token, user_id, csrf_token, ip_hash, user_agent, now, expires_at),
            )
            conn.commit()

        return session_token, csrf_token

    def get_user_by_session(self, session_token: str | None) -> tuple[User, str] | None:
        """Validate auth session token and return (User, csrf_token) if valid and not revoked."""
        if not session_token or not isinstance(session_token, str):
            return None

        clean_token = session_token.strip()
        now = time.time()

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT s.csrf_token, s.expires_at, s.revoked,
                       u.id, u.email, u.display_name, u.avatar_url,
                       u.account_status, u.email_verified, u.email_verified_at,
                       u.last_login_at, u.created_at, u.updated_at
                FROM user_sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_token = ? AND s.expires_at > ? AND s.revoked = 0
                """,
                (clean_token, now),
            ).fetchone()

        if not row:
            return None

        user = User(
            id=row["id"],
            email=row["email"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            account_status=row["account_status"],
            email_verified=bool(row["email_verified"]),
            email_verified_at=row["email_verified_at"],
            last_login_at=row["last_login_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        return user, row["csrf_token"]

    def logout(self, session_token: str | None) -> None:
        """Revoke active session."""
        if not session_token:
            return
        clean_token = session_token.strip()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "UPDATE user_sessions SET revoked = 1 WHERE session_token = ?", (clean_token,)
            )
            conn.commit()

    def revoke_all_user_sessions(self, user_id: str) -> None:
        """Revoke all sessions belonging to user_id."""
        with self._lock, self._get_connection() as conn:
            conn.execute("UPDATE user_sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
            conn.commit()

    # --- Google OAuth / Identity Provider Integration ---

    def authenticate_or_register_google_identity(
        self,
        sub: str,
        email: str,
        display_name: str | None = None,
        avatar_url: str | None = None,
        ip_hash: str | None = None,
    ) -> tuple[User, str, str]:
        """Authenticate or register user via verified Google identity token / userinfo.
        Uses Google sub as stable identifier.
        Safely prevents unverified account hijacking if email exists without linked Google identity.
        """
        clean_sub = str(sub).strip()
        clean_email = email.strip().lower()

        if not clean_sub:
            raise AuthError("Invalid Google subject identifier.", status_code=400)
        if not clean_email or not EMAIL_REGEX.match(clean_email):
            raise AuthError("Invalid Google email.", status_code=400)

        now = time.time()

        with self._lock, self._get_connection() as conn:
            # 1. Check if identity exists
            identity_row = conn.execute(
                """
                SELECT i.user_id, u.id, u.email, u.display_name, u.avatar_url,
                       u.account_status, u.email_verified, u.email_verified_at,
                       u.last_login_at, u.created_at, u.updated_at
                FROM user_identities i
                JOIN users u ON i.user_id = u.id
                WHERE i.provider = 'google' AND i.provider_user_id = ?
                """,
                (clean_sub,),
            ).fetchone()

            if identity_row:
                # Returning Google user
                user_id = identity_row["id"]
                conn.execute(
                    "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, user_id),
                )
                conn.commit()
                self.log_event(user_id, "google_login_returning", {"sub": clean_sub})
                user = User(
                    id=user_id,
                    email=identity_row["email"],
                    display_name=identity_row["display_name"],
                    avatar_url=identity_row["avatar_url"],
                    account_status=identity_row["account_status"],
                    email_verified=bool(identity_row["email_verified"]),
                    email_verified_at=identity_row["email_verified_at"],
                    last_login_at=now,
                    created_at=identity_row["created_at"],
                    updated_at=now,
                )
                session_token, csrf_token = self._create_session(user_id, ip_hash=ip_hash)
                return user, session_token, csrf_token

            # 2. Identity does not exist. Check if an account already exists with this email.
            existing_user = conn.execute(
                "SELECT id, email FROM users WHERE email = ?",
                (clean_email,),
            ).fetchone()

            if existing_user:
                # Account already exists via password. Do not automatically link!
                self.log_event(
                    existing_user["id"],
                    "google_login_conflict_unlinked",
                    {"email": clean_email, "sub": clean_sub},
                )
                raise AuthError(
                    "An account with this email already exists. Please log in with your DocuMind "
                    "password first to securely link your Google account.",
                    status_code=409,
                )

            # 3. First time Google user: create local account and identity record
            new_user_id = "usr_" + uuid.uuid4().hex[:16]
            identity_id = "idn_" + uuid.uuid4().hex[:16]
            resolved_name = display_name or clean_email.split("@")[0]

            conn.execute(
                """
                INSERT INTO users
                (id, email, display_name, avatar_url, account_status,
                 email_verified, email_verified_at, last_login_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)
                """,
                (new_user_id, clean_email, resolved_name, avatar_url, now, now, now, now),
            )
            conn.execute(
                """
                INSERT INTO user_identities
                (id, user_id, provider, provider_user_id, email, created_at)
                VALUES (?, ?, 'google', ?, ?, ?)
                """,
                (identity_id, new_user_id, clean_sub, clean_email, now),
            )
            conn.commit()

        self.log_event(
            new_user_id, "google_registration_created", {"sub": clean_sub, "email": clean_email}
        )
        user = User(
            id=new_user_id,
            email=clean_email,
            display_name=resolved_name,
            avatar_url=avatar_url,
            account_status="active",
            email_verified=True,
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
            updated_at=now,
        )
        session_token, csrf_token = self._create_session(new_user_id, ip_hash=ip_hash)
        return user, session_token, csrf_token

    def link_google_identity(self, user_id: str, sub: str, email: str) -> bool:
        """Securely link Google identity to an existing authenticated local user."""
        clean_sub = str(sub).strip()
        clean_email = email.strip().lower()
        now = time.time()
        identity_id = "idn_" + uuid.uuid4().hex[:16]

        with self._lock, self._get_connection() as conn:
            existing = conn.execute(
                (
                    "SELECT user_id FROM user_identities "
                    "WHERE provider = 'google' AND provider_user_id = ?"
                ),
                (clean_sub,),
            ).fetchone()
            if existing:
                if existing["user_id"] == user_id:
                    return True  # already linked to this user
                raise AuthError(
                    "This Google account is already linked to another user.", status_code=409
                )

            conn.execute(
                """
                INSERT INTO user_identities
                (id, user_id, provider, provider_user_id, email, created_at)
                VALUES (?, ?, 'google', ?, ?, ?)
                """,
                (identity_id, user_id, clean_sub, clean_email, now),
            )
            conn.commit()

        self.log_event(user_id, "google_identity_linked", {"sub": clean_sub})
        return True

    # --- Password Reset Flow ---

    def request_password_reset(self, email: str) -> str | None:
        """Generate single-use password reset token with 1-hour expiration.
        Returns the raw token (if user exists) for dispatch/testing.
        """
        clean_email = email.strip().lower()
        if not clean_email or not EMAIL_REGEX.match(clean_email):
            return None

        with self._lock, self._get_connection() as conn:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (clean_email,)).fetchone()
            if not row:
                self.log_event(None, "password_reset_nonexistent_email", {"email": clean_email})
                return None

            user_id = row["id"]
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            token_id = "rst_" + uuid.uuid4().hex[:16]
            now = time.time()
            expires_at = now + 3600  # 1 hour

            # Invalidate any prior unused tokens for this user
            conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE user_id = ?", (user_id,))
            conn.execute(
                """
                INSERT INTO password_reset_tokens
                (id, user_id, token_hash, expires_at, used, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (token_id, user_id, token_hash, expires_at, now),
            )
            conn.commit()

        self.log_event(user_id, "password_reset_requested", {})
        return raw_token

    def confirm_password_reset(self, raw_token: str, new_password: str) -> bool:
        """Validate reset token, update password hash, and revoke existing sessions."""
        if not raw_token or not raw_token.strip():
            raise AuthError("Invalid or missing reset token.", status_code=400)

        if len(new_password) < 10:
            raise AuthError("New password must be at least 10 characters long.", status_code=400)

        token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
        now = time.time()

        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, user_id, expires_at, used
                FROM password_reset_tokens
                WHERE token_hash = ? AND used = 0 AND expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()

            if not row:
                raise AuthError("Password reset token is invalid or has expired.", status_code=400)

            user_id = row["user_id"]
            salt = os.urandom(16)
            new_hash = self.hash_password(new_password, salt)

            # Update password
            conn.execute(
                "UPDATE users SET salt = ?, password_hash = ?, updated_at = ? WHERE id = ?",
                (salt, new_hash, now, user_id),
            )
            # Mark reset token as used
            conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE id = ?", (row["id"],))
            # Revoke all existing sessions for security
            conn.execute("UPDATE user_sessions SET revoked = 1 WHERE user_id = ?", (user_id,))
            conn.commit()

        self.log_event(user_id, "password_reset_completed", {})
        return True

    # --- Document Ownership & Access Control ---

    def record_document_owner(
        self,
        user_id: str,
        source: str,
        chunk_count: int,
        content_hash: str | None = None,
        storage_ref: str | None = None,
    ) -> None:
        """Register ownership of an indexed document for the authenticated user."""
        doc_id = "doc_" + uuid.uuid4().hex[:16]
        now = time.time()
        clean_source = source.strip()

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO documents
                (id, owner_id, source, content_hash, chunk_count, status,
                 storage_ref, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'indexed', ?, ?, ?)
                ON CONFLICT(owner_id, source) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    chunk_count = excluded.chunk_count,
                    status = 'indexed',
                    storage_ref = excluded.storage_ref,
                    updated_at = excluded.updated_at
                """,
                (doc_id, user_id, clean_source, content_hash, chunk_count, storage_ref, now, now),
            )
            conn.commit()

        self.log_event(
            user_id,
            "document_indexed",
            {"source": clean_source, "chunk_count": chunk_count},
        )

    def verify_document_owner(self, user_id: str, source: str) -> bool:
        """Check whether user_id is the legitimate owner of source."""
        clean_source = source.strip()
        with self._lock, self._get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM documents WHERE owner_id = ? AND source = ?",
                (user_id, clean_source),
            ).fetchone()
            return row is not None

    def delete_document_record(self, user_id: str, source: str) -> bool:
        """Delete document record owned by user_id."""
        clean_source = source.strip()
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM documents WHERE owner_id = ? AND source = ?",
                (user_id, clean_source),
            )
            conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            self.log_event(user_id, "document_deleted", {"source": clean_source})
        return deleted

    def get_user_documents(self, user_id: str) -> list[dict[str, Any]]:
        """List all documents owned by user_id."""
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, source, content_hash, chunk_count, status,
                       storage_ref, created_at, updated_at
                FROM documents
                WHERE owner_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "source": r["source"],
                    "content_hash": r["content_hash"],
                    "chunk_count": r["chunk_count"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                }
                for r in rows
            ]

    # --- Workspace & Guest Migration ---

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

            guest_uploads = guest_dir / "uploads"
            user_uploads = user_dir / "uploads"
            user_uploads.mkdir(parents=True, exist_ok=True)

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
                                indexed_doc = user_engine.index_text(content, doc_source, sha)
                                chunks = getattr(indexed_doc, "chunk_count", 0)
                                self.record_document_owner(
                                    user_id,
                                    doc_source,
                                    chunk_count=chunks,
                                    content_hash=sha,
                                )
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
            request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
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
