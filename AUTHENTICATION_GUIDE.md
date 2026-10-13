# DocuMind Authentication & User Database Architecture Guide

This guide documents the production-grade authentication, Google OAuth 2.0 / OpenID Connect integration, normalized user database, and tenant workspace isolation subsystem for DocuMind.

---

## 1. Architecture Overview

DocuMind enforces a **Glass Box** security model: zero secrets in client applications, strict server-side identity verification, defense-in-depth against credential stuffing and account hijacking, and tenant workspace isolation across all document and chat interactions.

```
┌────────────────────────────────────────────────────────┐
│                   DocuMind Frontend                    │
│   /app/auth.html   |   /app/console/   |   Library     │
└───────────────────────────┬────────────────────────────┘
                            │
               HTTPS / SameSite=Lax Cookies
                            │
┌───────────────────────────▼────────────────────────────┐
│                  FastAPI Auth Gateway                  │
│  /api/auth/register    |  /api/auth/login              │
│  /api/auth/logout      |  /api/auth/me                 │
│  /api/auth/google/*    |  /api/auth/password-reset/*   │
└─────────────┬───────────────────────────┬──────────────┘
              │                           │
┌─────────────▼─────────────┐   ┌─────────▼──────────────┐
│       AuthManager         │   │   Google OAuth 2.0     │
│  - scrypt password hash   │   │  - OpenID Connect      │
│  - Constant-time compare  │   │  - sub-claim binding   │
│  - CSRF state nonce       │   │  - Anti-takeover guard │
└─────────────┬─────────────┘   └────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────────┐
│      Normalized User Database (SQLite / Postgres)      │
│  users, user_identities, user_sessions, documents      │
│  conversations, messages, usage_events, reset_tokens   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Database Schema & Versioned Migrations

DocuMind uses a version-controlled migration engine (`documind/migrations/runner.py`) tracked in the `schema_migrations` table. It seamlessly supports **SQLite** for local development and **PostgreSQL** for scalable production deployments.

### Core Tables

| Table | Purpose | Indexes / Constraints |
| :--- | :--- | :--- |
| `users` | Primary identity record, normalized email, scrypt hash + salt | `UNIQUE(email)`, `account_status`, timestamps |
| `user_identities` | OAuth identity providers (e.g. `google`) | `UNIQUE(provider, provider_subject_id)`, `idx_identity_user` |
| `user_sessions` | Sliding session tokens with hash indexing | `UNIQUE(session_token_hash)`, `expires_at`, `revoked_at` |
| `documents` | User-owned document metadata and tenant mapping | `UNIQUE(user_id, source)`, foreign key cascade |
| `conversations` | Per-user conversation sessions | `idx_conv_user`, foreign key cascade |
| `messages` | Turn messages, citations, retrieved chunks, token metrics | `idx_msg_conv`, foreign key cascade |
| `usage_events` | Immutable security audit log for auth & upload events | `idx_usage_user`, `idx_usage_created` |
| `password_reset_tokens` | Single-use hashed tokens with 1-hour expiry | `UNIQUE(token_hash)`, `idx_password_reset_hash` |

To run or verify migrations:
```bash
python -c "from documind.migrations.runner import MigrationRunner; MigrationRunner('~/.documind/auth.db').run_all()"
```

---

## 3. Password & Session Security

- **Password Hashing**: Implemented using `hashlib.scrypt` with parameters:
  - `n=16384`, `r=8`, `p=1`, `maxmem=32 * 1024 * 1024`
  - Unique 16-byte cryptographically secure random salt per user (`os.urandom(16)`)
  - Minimum password length: 10 characters
  - Verified with constant-time equality via `hmac.compare_digest` to prevent timing attacks.
- **Session Tokens**:
  - Cryptographically secure 256-bit entropy tokens (`secrets.token_urlsafe(32)`).
  - Stored only as SHA-256 hashes in the database.
  - Stored in the browser via `HttpOnly`, `SameSite=Lax`, and `Secure` (in HTTPS/production) cookies (`documind_auth_session`).
  - Sliding TTL: Automatically extended on activity up to 7 days.
  - Revocation: Terminated immediately on logout or password reset.
- **Account Enumeration Defense**:
  - Registration with duplicate emails returns a generic error.
  - Failed login returns generic `"Invalid email or password"`.
  - Password recovery returns a generic success message regardless of whether the email exists.

---

## 4. Google OAuth 2.0 / OpenID Connect Setup

### Google Cloud Console Configuration
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Navigate to **APIs & Services** > **Credentials**.
3. Create an **OAuth 2.0 Client ID** (Web application).
4. Configure Authorized Origins:
   - `http://localhost:8000`
   - `http://127.0.0.1:8000`
   - (Your production domain)
5. Configure Authorized Redirect URIs:
   - `http://localhost:8000/api/auth/google/callback`
   - (Your production callback URL)
6. Copy the **Client ID** and **Client Secret** into your `.env` file:
   ```env
   DOCUMIND_REQUIRE_AUTH=1
   DOCUMIND_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
   DOCUMIND_GOOGLE_CLIENT_SECRET=your-client-secret
   DOCUMIND_GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
   ```

### Security Guarantees
- **No Client Secrets**: The Google client secret is never sent to or visible in the frontend.
- **Anti-CSRF State Nonce**: Authorize calls issue an opaque state parameter coupled with a temporary HttpOnly cookie (`documind_oauth_state`) carrying the intended redirect destination.
- **Immutable Subject ID Binding**: User identities are permanently bound to Google's verified `sub` claim, not the email address alone (protecting against account takeover via email address reassignment).
- **Collision Protection**: If a Google profile presents an email matching an unlinked local password account, the system rejects automatic linking with HTTP 409 / `account_exists_link_required`, prompting the user to authenticate with their password first.

---

## 5. Unified Authentication Portal

The frontend provides a single, high-fidelity entry point at `/app/auth.html`:
- **Glass Box Design**: Fully aligned with DocuMind design tokens:
  - Background: `#0e0e0e`
  - Accent Primary: `#ff571d`
  - Text: `#e5e2e1`
  - Fonts: *Inter* (UI) and *JetBrains Mono* (Code / Technical Data)
- **Features**:
  - Sign In with Email & Password.
  - Create Account with display name and password confirmation.
  - Continue with Google (official multi-color SVG branding).
  - Forgot Password request & token confirmation flows.
  - Error and status notification banners (e.g. `?reason=auth_required`, `?error=invalid_state`).
  - Seamless return redirects via `?redirect=...`.
  - Accessible tab switching, field validation, and reduced-motion animations.

---

## 6. Tenant Workspace & Document Isolation

- Anonymous access to document indexing (`POST /api/demo/documents`), deletion (`DELETE /api/demo/documents/{source}`), listing (`GET /api/demo/documents`), and chunk inspection (`GET /api/demo/documents/{source}/chunks`) is blocked with **HTTP 401 Unauthorized**.
- Each authenticated user operates in their own isolated tenant workspace:
  - User A cannot view User B's documents or chunks.
  - User A cannot delete User B's documents.
  - Vector similarity search strictly scopes queries to the authenticated tenant's document index.

---

## 7. Automated Test Verification

A dedicated end-to-end test suite validates all security invariants:

```bash
# Run complete authentication and isolation test suite
.venv/bin/pytest tests/test_auth_complete.py -v

# Run full auth test suite
.venv/bin/pytest tests/test_auth.py tests/test_auth_complete.py -v

# Run code style and type safety quality gates
.venv/bin/ruff check .
.venv/bin/mypy documind
```
