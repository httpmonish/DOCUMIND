"""documind/migrations/runner.py
Version-controlled database schema migration runner for DocuMind.
Supports SQLite (local development / test) and PostgreSQL (production).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "0001_initial_auth_and_user_schema",
        [
            # Users table
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                display_name TEXT,
                avatar_url TEXT,
                account_status TEXT NOT NULL DEFAULT 'active',
                salt BLOB,
                password_hash BLOB,
                email_verified INTEGER NOT NULL DEFAULT 0,
                email_verified_at REAL,
                last_login_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """,
            # External identity provider associations (e.g., Google OAuth)
            """
            CREATE TABLE IF NOT EXISTS user_identities (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                email TEXT,
                created_at REAL NOT NULL,
                UNIQUE(provider, provider_user_id)
            );
            """,
            # Revocable authenticated user sessions
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                ip_hash TEXT,
                user_agent TEXT,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            );
            """,
            # User-owned documents with ownership tracking
            """
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                content_hash TEXT,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'indexed',
                storage_ref TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(owner_id, source)
            );
            """,
            # Conversations associated with authenticated owner
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """,
            # Chat messages within conversations
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                citations TEXT,
                created_at REAL NOT NULL
            );
            """,
            # Usage events and audit logs
            """
            CREATE TABLE IF NOT EXISTS usage_events (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                event_type TEXT NOT NULL,
                metadata TEXT,
                created_at REAL NOT NULL
            );
            """,
            # Single-use password reset tokens with expiry
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT UNIQUE NOT NULL,
                expires_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            """,
            # Performance & lookup indexes
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);",
            "CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_id);",
            "CREATE INDEX IF NOT EXISTS idx_conversations_owner ON conversations(owner_id);",
            "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);",
            "CREATE INDEX IF NOT EXISTS idx_usage_events_user ON usage_events(user_id);",
            (
                "CREATE INDEX IF NOT EXISTS idx_password_reset_hash ON "
                "password_reset_tokens(token_hash);"
            ),
        ],
    ),
    (
        2,
        "0002_compat_views_and_columns",
        [
            # Add updated_at or status columns if existing table lacked them
            """
            CREATE VIEW IF NOT EXISTS auth_sessions AS
            SELECT session_token, user_id, csrf_token, created_at, expires_at
            FROM user_sessions WHERE revoked = 0;
            """
        ],
    ),
    (
        3,
        "0003_add_user_display_name_and_status",
        [
            "ALTER TABLE users ADD COLUMN display_name TEXT;",
            "ALTER TABLE users ADD COLUMN avatar_url TEXT;",
            "ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'active';",
            "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN email_verified_at REAL;",
            "ALTER TABLE users ADD COLUMN last_login_at REAL;",
            "ALTER TABLE users ADD COLUMN updated_at REAL;",
        ],
    ),
    (
        4,
        "0004_document_and_conversation_persistence",
        [
            "ALTER TABLE documents ADD COLUMN display_name TEXT;",
            "ALTER TABLE documents ADD COLUMN file_type TEXT;",
            "ALTER TABLE documents ADD COLUMN mime_type TEXT;",
            "ALTER TABLE documents ADD COLUMN file_size INTEGER DEFAULT 0;",
            "ALTER TABLE documents ADD COLUMN storage_key TEXT;",
            "ALTER TABLE documents ADD COLUMN processing_error TEXT;",
            "ALTER TABLE documents ADD COLUMN chromadb_collection TEXT;",
            "ALTER TABLE documents ADD COLUMN last_accessed_at REAL;",
            "ALTER TABLE documents ADD COLUMN deleted_at REAL;",
            "ALTER TABLE conversations ADD COLUMN session_hash TEXT;",
            "ALTER TABLE conversations ADD COLUMN document_id TEXT;",
            "ALTER TABLE conversations ADD COLUMN last_message_at REAL;",
            "ALTER TABLE conversations ADD COLUMN archived_at REAL;",
            "ALTER TABLE conversations ADD COLUMN deleted_at REAL;",
            "ALTER TABLE messages ADD COLUMN updated_at REAL;",
            "ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'completed';",
            "ALTER TABLE messages ADD COLUMN metadata TEXT;",
            (
                "CREATE INDEX IF NOT EXISTS idx_documents_owner_accessed "
                "ON documents(owner_id, last_accessed_at);"
            ),
            (
                "CREATE INDEX IF NOT EXISTS idx_conversations_owner_activity "
                "ON conversations(owner_id, last_message_at);"
            ),
            "CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_hash);",
            (
                "CREATE INDEX IF NOT EXISTS idx_messages_conv_created "
                "ON messages(conversation_id, created_at);"
            ),
        ],
    ),
    (
        5,
        "0005_saas_monetization_and_quotas",
        [
            # User quotas & allowances table
            """
            CREATE TABLE IF NOT EXISTS user_quotas (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                plan_id TEXT NOT NULL DEFAULT 'free',
                doc_limit INTEGER NOT NULL DEFAULT 1,
                consumed_docs INTEGER NOT NULL DEFAULT 0,
                question_limit INTEGER NOT NULL DEFAULT 5,
                consumed_questions INTEGER NOT NULL DEFAULT 0,
                reserved_questions INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """,
            # Subscriptions table
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                provider TEXT NOT NULL DEFAULT 'razorpay',
                provider_subscription_id TEXT,
                current_period_start REAL,
                current_period_end REAL,
                cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """,
            # Quota events log (atomic reservation and audit trail)
            """
            CREATE TABLE IF NOT EXISTS quota_events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'reserved',
                request_id TEXT NOT NULL,
                resource_id TEXT,
                reason TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            """,
            # Replay protection table for payment webhooks
            """
            CREATE TABLE IF NOT EXISTS processed_webhooks (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload TEXT,
                processed_at REAL NOT NULL
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);",
            (
                "CREATE INDEX IF NOT EXISTS idx_quota_events_user_req "
                "ON quota_events(user_id, request_id);"
            ),
            "CREATE INDEX IF NOT EXISTS idx_quota_events_req ON quota_events(request_id);",
        ],
    ),
]


class MigrationRunner:
    """Applies versioned schema migrations against SQLite or PostgreSQL."""

    def __init__(self, db_path: Path | str, database_url: str = "") -> None:
        self.db_path = Path(db_path).resolve() if not database_url else None
        self.database_url = database_url.strip()

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        if self.db_path is None:
            raise ValueError("SQLite database path is required when database_url is not set.")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def run_migrations(self) -> list[str]:
        """Apply all pending migrations in order."""
        if self.database_url and (
            self.database_url.startswith("postgresql://")
            or self.database_url.startswith("postgres://")
        ):
            return self._run_postgresql_migrations()

        return self._run_sqlite_migrations()

    def _run_sqlite_migrations(self) -> list[str]:
        applied_names: list[str] = []
        with self._get_sqlite_connection() as conn:
            # Ensure schema_migrations table exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at REAL NOT NULL
                );
                """
            )
            conn.commit()

            # Inspect current applied versions
            cursor = conn.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
            applied_versions = {row["version"] for row in cursor.fetchall()}

            # Ensure user_quotas matches canonical schema (self-healing for draft DBs)
            cursor = conn.execute("PRAGMA table_info(user_quotas)")
            quota_cols = {row["name"] for row in cursor.fetchall()}
            if quota_cols and "doc_limit" not in quota_cols:
                conn.execute("DROP TABLE IF EXISTS user_quotas")
                conn.execute("DELETE FROM schema_migrations WHERE version = 5")
                conn.commit()
                applied_versions.discard(5)

            for version, name, statements in MIGRATIONS:
                if version in applied_versions:
                    continue

                logger.info("Applying database migration %d: %s", version, name)
                for sql in statements:
                    try:
                        conn.execute(sql)
                    except sqlite3.OperationalError as e:
                        # Handle cases where column or view might already exist
                        if (
                            "already exists" in str(e).lower()
                            or "duplicate column" in str(e).lower()
                        ):
                            continue
                        logger.warning("Migration %s statement warning: %s", name, e)

                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, time.time()),
                )
                conn.commit()
                applied_names.append(name)

        return applied_names

    def _run_postgresql_migrations(self) -> list[str]:
        """Runs migrations when PostgreSQL connection is configured."""
        try:
            import psycopg2  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("psycopg2 not installed; falling back to SQLite migration runner.")
            return self._run_sqlite_migrations()

        applied_names: list[str] = []
        conn = psycopg2.connect(self.database_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        applied_at DOUBLE PRECISION NOT NULL
                    );
                    """
                )
                conn.commit()
                cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
                applied_versions = {row[0] for row in cur.fetchall()}

                for version, name, statements in MIGRATIONS:
                    if version in applied_versions:
                        continue
                    logger.info("Applying PostgreSQL migration %d: %s", version, name)
                    for sql in statements:
                        # Translate basic SQLite types if necessary
                        pg_sql = (
                            sql.replace("BLOB", "BYTEA")
                            .replace("REAL", "DOUBLE PRECISION")
                            .replace("INTEGER PRIMARY KEY", "SERIAL PRIMARY KEY")
                        )
                        cur.execute(pg_sql)
                    cur.execute(
                        (
                            "INSERT INTO schema_migrations (version, name, applied_at) "
                            "VALUES (%s, %s, %s)"
                        ),
                        (version, name, time.time()),
                    )
                    conn.commit()
                    applied_names.append(name)
        finally:
            conn.close()

        return applied_names
