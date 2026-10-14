# DocuMind — Render Deployment Guide

This guide details how to deploy DocuMind as a production-hardened, Docker-based Web Service on [Render](https://render.com).

---

## 1. Architecture & Render Overview

DocuMind is packaged as a multi-stage, unprivileged Linux container (`python:3.11-slim`, non-root user `documind:documind`, UID `10001`):

- **Web Server:** FastAPI running on Uvicorn with native proxy header support (`--proxy-headers --forwarded-allow-ips "*"`).
- **Frontend Delivery:** Static assets served with same-origin semantics (`/app` and `/` redirecting to `/app/console/code.html`).
- **Storage Layer:** ChromaDB vector index, SQLite databases (`auth.db`, `chat.db`, `spend_ledger.db`), session subdirectories, and uploaded PDF/TXT/MD files live under a single unified persistent root: `DOCUMIND_HOME=/app/data`.
- **Dynamic Port:** The container binds to `0.0.0.0` and listens on the port dynamically assigned by Render via `${PORT:-8000}`, with fallback to `8000` for local development.

---

## 2. Resource & Instance Plan Requirements

> [!IMPORTANT]
> **Recommended Render Plan: Starter ($7/month) or higher with a Persistent Disk.**
> 
> - **RAM Requirement:** The local embedding model (`BAAI/bge-small-en-v1.5`) and ChromaDB vector store require **~450MB – 650MB RAM** at baseline. The Render Free tier (512MB RAM ceiling) risks encountering Linux Out-Of-Memory termination (`exit code 137`) during concurrent indexing.
> - **Persistent Disk:** Render Free tier does not support persistent disks. All user registrations, document collections, and vector embeddings would reset on restart. The Starter plan allows attaching a dedicated Persistent Disk mounted at `/app/data`.

---

## 3. Persistent Disk Configuration

Attach a Render Persistent Disk to your Web Service with the following exact parameters:

| Property | Value | Notes |
|:---|:---|:---|
| **Disk Name** | `documind-data` | Any identifier |
| **Mount Path** | `/app/data` | **Required.** Matches `DOCUMIND_HOME=/app/data` |
| **Size** | `10 GB` (or larger) | Holds ChromaDB vectors, SQLite databases, and uploaded PDFs |

### What is stored on the Persistent Disk:
- `/app/data/chroma/` — ChromaDB persistent vector database and `meta.json`.
- `/app/data/auth.db` — User accounts, password hashes (bcrypt), token quotas, and active subscriptions.
- `/app/data/chat.db` — Multi-turn conversation sessions and messages.
- `/app/data/spend_ledger.db` — Daily spend tracking and rate limiting ledgers.
- `/app/data/uploads/` — Uploaded original documents.
- `/app/data/sessions/` — Isolated tenant session trees.
- `/app/data/logs/` — Structured query audit logs.

---

## 4. Environment Variables Reference

Configure these environment variables in your Render Web Service settings (**Environment** tab):

### Mandatory Settings

| Variable | Recommended / Required Value | Purpose |
|:---|:---|:---|
| `DOCUMIND_ENV` | `production` | Enables production security policies and hides `/docs` |
| `DOCUMIND_HOME` | `/app/data` | Root path for persistent data (must match disk mount path) |
| `DOCUMIND_API_KEY` | *(Generate 32+ character random hex)* | Master API key for administrative `/v1/*` routes |
| `DOCUMIND_SESSION_SECRET` | *(Generate 32+ character random hex)* | Key for signing session tokens and authentication cookies |
| `DOCUMIND_REQUIRE_AUTH` | `1` | Enforces user registration and login |
| `DOCUMIND_ALLOW_GUEST_UPLOAD` | `0` | Disables anonymous uploads (requires user login/registration) |

### LLM Provider Selection (Choose One)

| Variable | Value Options | Description & Estimated Cost |
|:---|:---|:---|
| `DOCUMIND_LLM_PROVIDER` | `none` | **Free / Zero-Cost:** Grounded evidence retrieval with cited chunks and direct document exploration. No third-party LLM API key required. |
| `DOCUMIND_LLM_PROVIDER` | `gemini` | **Google Gemini:** High speed, generous free tier. Requires `GEMINI_API_KEY` (Google AI Studio). Default model: `gemini-3.5-flash`. |
| `DOCUMIND_LLM_PROVIDER` | `anthropic` | **Anthropic Claude:** Default production LLM. Requires `ANTHROPIC_API_KEY`. Default model: `claude-haiku-4-5-20251001`. |
| `DOCUMIND_LLM_PROVIDER` | `openrouter` | **OpenRouter:** Access to Llama 3.1, Mistral, etc. Requires `OPENROUTER_API_KEY`. |
| `DOCUMIND_LLM_PROVIDER` | `openai_compat` | **OpenAI Compatible:** Supports Groq, Together, DeepSeek, or self-hosted vLLM. Requires `DOCUMIND_OPENAI_API_KEY` and `DOCUMIND_OPENAI_BASE_URL`. |

### Optional Provider Credentials

| Variable | Description |
|:---|:---|
| `ANTHROPIC_API_KEY` | Required if `DOCUMIND_LLM_PROVIDER=anthropic`. Format: `sk-ant-...` |
| `GEMINI_API_KEY` | Required if `DOCUMIND_LLM_PROVIDER=gemini`. Format: `AQ...` |
| `OPENROUTER_API_KEY` | Required if `DOCUMIND_LLM_PROVIDER=openrouter`. Format: `sk-or-v1-...` |
| `DOCUMIND_MODEL` | Override default model name for chosen provider |

### Optional SaaS Monetization (Razorpay)

| Variable | Description |
|:---|:---|
| `RAZORPAY_KEY_ID` | Razorpay public Key ID (`rzp_live_...` or `rzp_test_...`) |
| `RAZORPAY_KEY_SECRET` | Razorpay private Secret Key |
| `RAZORPAY_WEBHOOK_SECRET` | Secret key for verifying HMAC-SHA256 signatures on billing webhooks |
| `DOCUMIND_FREE_DOC_LIMIT` | Lifetime document indexing limit for free tier accounts (default: `1`) |
| `DOCUMIND_FREE_QUESTION_LIMIT` | Question allowance for free tier accounts (default: `5`) |

---

## 5. Deployment Methods on Render

### Method A: Deploy via Render Blueprint (`render.yaml`) — Recommended

1. Fork or push this repository to your GitHub account: `https://github.com/httpmonish/DOCUMIND`.
2. Log into the [Render Dashboard](https://dashboard.render.com).
3. Click **New +** ➔ **Blueprint**.
4. Connect your `DOCUMIND` repository.
5. Render reads [`render.yaml`](../render.yaml) automatically:
   - Configures Web Service with Docker runtime.
   - Generates cryptographically secure 32+ character secrets for `DOCUMIND_API_KEY` and `DOCUMIND_SESSION_SECRET`.
   - Creates and mounts the `documind-data` 10 GB persistent disk at `/app/data`.
6. Add your LLM provider key (e.g. `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`) if you want synthesized answers.
7. Click **Apply**. Render will build and deploy the container.

---

### Method B: Manual Web Service Setup via Render Dashboard

1. In Render Dashboard, click **New +** ➔ **Web Service**.
2. Connect your repository (`httpmonish/DOCUMIND`).
3. Fill in the service settings:
   - **Name:** `documind` (or your chosen name)
   - **Language / Runtime:** `Docker`
   - **Region:** Any (e.g., `Oregon, USA` or `Frankfurt, EU`)
   - **Branch:** `main` (or `feature/mcp-server`)
   - **Root Directory:** `.` (leave default)
   - **Instance Type:** `Starter` ($7/mo)
4. Under **Disks**:
   - Click **Add Disk**.
   - **Name:** `documind-data`
   - **Mount Path:** `/app/data`
   - **Size:** `10 GB`
5. Under **Environment Variables**, add the keys listed in Section 4.
6. Under **Health Check Path**, enter: `/healthz`.
7. Click **Create Web Service**.

---

## 6. Verification & Health Monitoring

Once deployed:

1. **Health Probe:**
   Visit `https://<your-service>.onrender.com/healthz`
   Expected response:
   ```json
   {
     "status": "ok",
     "index_chunks": 0,
     "embed_model": "BAAI/bge-small-en-v1.5",
     "schema_version": 1,
     "tau": 0.35
   }
   ```
2. **Frontend Console:**
   Navigate to `https://<your-service>.onrender.com/` — it automatically redirects to `/app/console/code.html`.
3. **Authentication & Upload:**
   - Click **Register** to create an account.
   - Test uploading a PDF document.
   - Verify indexing and chunk generation.
   - Ask a question to verify grounded citation and answer synthesis.
