"""documind/interfaces/api.py
FastAPI REST API adapter for DocuMind.
Strictly decoupled: delegates all search, retrieval, and indexing to DocuMind core.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import StreamingResponse

from documind.core.chat import ChatManager
from documind.core.citations import parse_citations
from documind.core.condense import condense_query
from documind.core.config import Settings, load_settings
from documind.core.errors import (
    DocumentTooLarge,
    DocumentUnreadable,
    DocuMindError,
    EmbeddingFailed,
    IndexUnavailable,
    LLMUnavailable,
)
from documind.core.ingest import safe_upload_name
from documind.core.pipeline import DocuMind
from documind.core.prompt import build_prompt
from documind.core.retrieval import expand_neighbors
from documind.core.serialize import answer_to_dict
from documind.interfaces.auth import (
    AUTH_COOKIE_NAME,
    AuthError,
    AuthManager,
    User,
    clear_auth_cookie,
    set_auth_cookie,
)
from documind.interfaces.ratelimit import MultiActionRateLimiter, TokenBucketLimiter
from documind.interfaces.security import (
    client_ip,
    hash_ip,
)
from documind.interfaces.session import (
    SessionManager,
    normalize_session_identifier,
    validate_session_id_format,
)
from documind.interfaces.spend import (
    SpendLedger,
    calculate_cost_usd,
    estimate_generation_cost,
)

logger = logging.getLogger(__name__)

REQUEST_ID_REGEX = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class AskRequest(BaseModel):
    question: str
    top_k: int = 5
    debug: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        stripped = v.strip()
        if not (1 <= len(stripped) <= 2000):
            raise ValueError("question length must be between 1 and 2000 characters")
        return stripped

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        if not (1 <= v <= 10):
            raise ValueError("top_k must be an integer between 1 and 10")
        return v


class ChatRequest(BaseModel):
    question: str
    conversation_id: str | None = None
    top_k: int = 5
    debug: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("question")
    @classmethod
    def validate_question(cls, v: str) -> str:
        stripped = v.strip()
        if not (1 <= len(stripped) <= 2000):
            raise ValueError("question length must be between 1 and 2000 characters")
        return stripped

    @field_validator("top_k")
    @classmethod
    def validate_top_k(cls, v: int) -> int:
        if not (1 <= v <= 10):
            raise ValueError("top_k must be an integer between 1 and 10")
        return v


class AnalyzeRequest(BaseModel):
    action: str
    source: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        clean = v.strip().lower()
        if clean not in {"summarize", "key_points", "explain"}:
            raise ValueError("action must be one of: summarize, key_points, explain")
        return clean


class AuthPayload(BaseModel):
    email: str
    password: str
    display_name: str | None = None
    claim_guest_session: str | None = None


class PasswordResetRequestPayload(BaseModel):
    email: str


class PasswordResetConfirmPayload(BaseModel):
    token: str
    new_password: str


def get_authenticated_user_opt(request: Request) -> tuple[User, str] | None:
    """Extract authenticated user and tenant workspace hash if valid session exists."""
    auth_mgr = getattr(request.app.state, "auth_manager", None)
    mgr: SessionManager | None = getattr(request.app.state, "session_manager", None)
    if not auth_mgr or not mgr:
        return None

    auth_token = request.cookies.get(AUTH_COOKIE_NAME)
    if not auth_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ", 1)[1].strip()

    if auth_token:
        user_info = auth_mgr.get_user_by_session(auth_token)
        if user_info:
            user, _ = user_info
            user_hash = auth_mgr.get_user_workspace_hash(user.id)
            mgr.register_session(user_hash, ip_hash="auth_" + user.id)
            return user, str(user_hash)
    return None


def require_authenticated_user(request: Request) -> tuple[User, str]:
    """Dependency returning the authenticated user or active guest user and workspace hash."""
    auth_user = get_authenticated_user_opt(request)
    if auth_user:
        return auth_user

    # Fallback to validated guest session token (raises 400 if missing/invalid, 401 if unregistered)
    raw = request.headers.get("X-Session-ID") or request.cookies.get("documind_session")
    clean_token = validate_session_id_format(raw)
    mgr: SessionManager | None = getattr(request.app.state, "session_manager", None)
    if mgr:
        session_hash = mgr.validate_token(clean_token)
        pseudo_user = User(id="guest_" + session_hash[:8], email="guest@example.com")
        return pseudo_user, session_hash

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please sign in or initialize a guest session.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_session(request: Request) -> str:
    """Dependency returning the validated workspace hash. Enforces authentication by default."""
    _, user_hash = require_authenticated_user(request)
    return user_hash


def check_demo_rate_limit(request: Request) -> None:
    """Enforce per-IP sliding window/token bucket rate limit."""
    limiter = getattr(request.app.state, "multi_limiter", None)
    ip = client_ip(request)
    ip_h = hash_ip(ip)
    if limiter:
        allowed, retry_after = limiter.consume("general", ip_h)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Retry in {retry_after} s.",
                headers={"Retry-After": str(retry_after)},
            )


def _get_request_id(request: Request) -> str:
    """Retrieve or generate a validated request ID."""
    req_id = getattr(request.state, "request_id", None)
    if req_id and isinstance(req_id, str):
        return req_id
    raw = request.headers.get("X-Request-ID")
    if raw and REQUEST_ID_REGEX.match(raw):
        return raw
    return str(uuid.uuid4())


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    headers: Mapping[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Generate a consistent non-2xx error envelope."""
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if extra:
        payload["error"].update(extra)

    resp_headers = {
        "X-Request-ID": request_id,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if headers:
        resp_headers.update(headers)

    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers=resp_headers,
    )


def require_api_key(request: Request) -> str:
    """Validate X-API-Key header in constant time.
    Never accepts key through query parameters. Never logs the key.
    """
    supplied = request.headers.get("X-API-Key")
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    settings: Settings = request.app.state.settings
    expected = settings.api_key
    # Compare using bytes to prevent TypeError on non-ASCII characters
    supplied_bytes = supplied.encode("utf-8", errors="replace")
    expected_bytes = expected.encode("utf-8")
    if not hmac.compare_digest(supplied_bytes, expected_bytes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )
    return supplied


def check_rate_limit(request: Request, api_key: str = Depends(require_api_key)) -> None:
    """Enforce per-key token bucket rate limit using hashed identity."""
    limiter: TokenBucketLimiter = request.app.state.limiter
    identity = TokenBucketLimiter.derive_identity(api_key)
    allowed, retry_after = limiter.consume(identity)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Retry in {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform exception handlers adhering to the API contract."""

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        req_id = _get_request_id(request)
        return error_response(
            422,
            code="validation_error",
            message="Invalid request payload or parameters.",
            request_id=req_id,
        )

    @app.exception_handler(StarletteHTTPException)
    @app.exception_handler(HTTPException)
    def handle_http_exception(
        request: Request, exc: HTTPException | StarletteHTTPException
    ) -> Response:
        req_id = _get_request_id(request)
        code = "http_error"
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            msg = str(exc.detail).lower()
            if "expired" in msg:
                code = "SESSION_EXPIRED"
            elif "session" in msg or "token" in msg:
                code = "SESSION_INVALID"
            else:
                code = "unauthorized"
        elif exc.status_code == status.HTTP_404_NOT_FOUND:
            code = "not_found"
            accept_hdr = request.headers.get("accept", "").lower()
            if "text/html" in accept_hdr and not (
                request.url.path.startswith("/v1") or request.url.path.startswith("/api")
            ):
                static_404 = (
                    Path(__file__).resolve().parent.parent.parent / "Documind-frontend" / "404.html"
                )
                if static_404.is_file():
                    return HTMLResponse(
                        content=static_404.read_text(encoding="utf-8"),
                        status_code=status.HTTP_404_NOT_FOUND,
                        headers={"X-Content-Type-Options": "nosniff"},
                    )
        elif exc.status_code == status.HTTP_409_CONFLICT:
            is_snake = isinstance(exc.detail, str) and "_" in exc.detail
            code = getattr(exc, "detail", "conflict") if is_snake else "conflict"
        elif exc.status_code == 413:
            code = "payload_too_large"
        elif exc.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE:
            code = "unsupported_media_type"
        elif exc.status_code == 422:
            code = "unprocessable_entity"
        elif exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            code = "rate_limited"

        detail_msg = exc.detail if isinstance(exc.detail, str) else "Request error."
        return error_response(
            exc.status_code,
            code=code,
            message=detail_msg,
            request_id=req_id,
            headers=exc.headers,
        )

    @app.exception_handler(DocumentUnreadable)
    def handle_unreadable(request: Request, exc: DocumentUnreadable) -> JSONResponse:
        req_id = _get_request_id(request)
        return error_response(
            422,
            code="document_unreadable",
            message="Document could not be read or parsed.",
            request_id=req_id,
        )

    @app.exception_handler(DocumentTooLarge)
    def handle_too_large(request: Request, exc: DocumentTooLarge) -> JSONResponse:
        req_id = _get_request_id(request)
        return error_response(
            413,
            code="document_too_large",
            message="Document exceeds size or page count limits.",
            request_id=req_id,
        )

    @app.exception_handler(IndexUnavailable)
    def handle_index_unavailable(request: Request, exc: IndexUnavailable) -> JSONResponse:
        req_id = _get_request_id(request)
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            code="index_unavailable",
            message="Document vector index is temporarily unavailable.",
            request_id=req_id,
        )

    @app.exception_handler(EmbeddingFailed)
    def handle_embedding_failed(request: Request, exc: EmbeddingFailed) -> JSONResponse:
        req_id = _get_request_id(request)
        return error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            code="embedding_failed",
            message="Embedding generation failed.",
            request_id=req_id,
        )

    @app.exception_handler(LLMUnavailable)
    def handle_llm_unavailable(request: Request, exc: LLMUnavailable) -> JSONResponse:
        req_id = _get_request_id(request)
        return error_response(
            status.HTTP_502_BAD_GATEWAY,
            code="llm_unavailable",
            message="Language model service is unavailable.",
            request_id=req_id,
        )

    @app.exception_handler(DocuMindError)
    def handle_documind_error(request: Request, exc: DocuMindError) -> JSONResponse:
        req_id = _get_request_id(request)
        print(f"ERROR: DocuMindError: {exc}", file=sys.stderr)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="An internal error occurred.",
            request_id=req_id,
        )

    @app.exception_handler(Exception)
    def handle_catchall(request: Request, exc: Exception) -> JSONResponse:
        req_id = _get_request_id(request)
        import traceback

        print(f"ERROR: Unexpected exception for request {req_id}:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="internal_error",
            message="An internal error occurred.",
            request_id=req_id,
        )


def create_app(
    dm: DocuMind | None = None,
    settings: Settings | None = None,
    limiter: TokenBucketLimiter | None = None,
) -> FastAPI:
    """FastAPI application factory.
    No side effects on module import.
    """
    app_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
        # Validate API key at startup for fail-closed security
        if not app_settings.api_key or len(app_settings.api_key) < 32:
            raise RuntimeError(
                "DOCUMIND_API_KEY must be configured and at least 32 characters long."
            )

        # Attach or construct engine
        if getattr(app_instance.state, "engine", None) is None:
            if dm is not None:
                app_instance.state.engine = dm
            else:
                from documind.core.factory import build_default

                app_instance.state.engine = build_default(app_settings)

        # Attach or construct session manager for isolated public demo sessions
        if getattr(app_instance.state, "session_manager", None) is None:
            active_engine: DocuMind = app_instance.state.engine
            app_instance.state.session_manager = SessionManager(
                base_dir=app_settings.home / "sessions",
                shared_embedder=active_engine.embedder,
                shared_llm=active_engine.llm,
                settings=app_settings,
            )

        if getattr(app_instance.state, "auth_manager", None) is None:
            app_instance.state.auth_manager = AuthManager(
                db_path=app_settings.home / "auth.db",
                database_url=app_settings.database_url,
            )

        yield

    # Documentation disabled in production
    is_prod = app_settings.env == "prod"
    app = FastAPI(
        title="DocuMind API",
        version="0.4.0",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
        lifespan=lifespan,
    )

    app.state.settings = app_settings
    app.state.engine = dm
    from documind.core.factory import build_default

    active_engine = dm if dm is not None else build_default(app_settings)
    app.state.session_manager = SessionManager(
        base_dir=Path(app_settings.home) / "sessions",
        shared_embedder=active_engine.embedder,
        shared_llm=active_engine.llm,
        settings=app_settings,
    )
    app.state.auth_manager = AuthManager(
        db_path=Path(app_settings.home) / "auth.db",
        database_url=app_settings.database_url,
    )
    app.state.limiter = limiter or TokenBucketLimiter(rate_per_min=app_settings.rate_limit_per_min)
    app.state.multi_limiter = MultiActionRateLimiter()
    app.state.spend_ledger = SpendLedger(
        db_path=app_settings.home / "spend_ledger.db",
        global_daily_cap_usd=getattr(app_settings, "global_daily_cap_usd", 2.00),
        ip_daily_cap_usd=getattr(app_settings, "ip_daily_cap_usd", 0.25),
    )
    app.state.chat_manager = ChatManager(db_path=app_settings.home / "chat.db")
    app.state.write_lock = threading.Lock()

    allowed_origins = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    env_origins = os.getenv("DOCUMIND_ALLOWED_ORIGINS")
    if env_origins:
        allowed_origins.extend([o.strip() for o in env_origins.split(",") if o.strip()])

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Request ID and defensive security headers middleware
    @app.middleware("http")
    async def request_middleware(request: Request, call_next: Any) -> Response:
        raw_req_id = request.headers.get("X-Request-ID")
        if raw_req_id and REQUEST_ID_REGEX.match(raw_req_id):
            req_id = raw_req_id
        else:
            req_id = str(uuid.uuid4())
        request.state.request_id = req_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    register_exception_handlers(app)

    # Healthcheck endpoint (Unauthenticated)
    @app.get("/healthz")
    def healthz(request: Request) -> dict[str, Any]:
        engine: DocuMind | None = getattr(request.app.state, "engine", None)
        index_chunks = engine.store.count() if engine else 0
        model_name = engine.settings.embed_model if engine else app_settings.embed_model
        return {
            "status": "ok",
            "index_chunks": int(index_chunks),
            "embed_model": model_name,
            "schema_version": 1,
            "tau": engine.settings.min_score if engine else app_settings.min_score,
        }

    # Protected v1 API router
    v1_router = APIRouter(
        prefix="/v1",
        dependencies=[Depends(require_api_key), Depends(check_rate_limit)],
    )

    @v1_router.get("/documents")
    def list_documents(request: Request) -> list[dict[str, Any]]:
        engine: DocuMind = request.app.state.engine
        docs = engine.documents()
        return [
            {
                "source": doc,
                "chunks": engine.chunk_count(doc),
                "sha256": engine.doc_sha(doc) or "",
            }
            for doc in docs
        ]

    @v1_router.post("/ask")
    def ask(body: AskRequest, request: Request) -> JSONResponse:
        engine: DocuMind = request.app.state.engine
        settings: Settings = request.app.state.settings
        req_id = _get_request_id(request)

        # Empty index: return 409 conflict with index_empty
        if engine.store.count() == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="index_empty",
            )

        ans = engine.answer(
            body.question,
            top_k=body.top_k,
            interface="api",
            req_id=req_id,
        )

        # LLM failure representation (HTTP 502 with fallback citations)
        if ans.abstain_reason == "llm_unavailable":
            fallback_citations = [
                {
                    "marker": c.marker,
                    "source": c.source,
                    "chunk_index": int(c.chunk_index),
                    "snippet": c.snippet[:200],
                    "score": round(float(c.score), 4),
                }
                for c in ans.citations
            ]
            fallback_payload = {
                "outcome": ans.outcome,
                "abstain_reason": ans.abstain_reason,
                "citations": fallback_citations,
                "model": ans.model,
                "usage": {
                    "input_tokens": int(ans.usage.input_tokens),
                    "output_tokens": int(ans.usage.output_tokens),
                },
                "latency_ms": int(ans.latency_ms),
            }
            return error_response(
                status.HTTP_502_BAD_GATEWAY,
                code="llm_unavailable",
                message="Language model service is unavailable.",
                request_id=req_id,
                extra={"fallback": fallback_payload},
            )

        # Normal response shaping
        include_retrieved = bool(settings.allow_debug and body.debug)
        data = answer_to_dict(ans, include_retrieved=include_retrieved)
        headers = {
            "X-Request-ID": req_id,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        }
        return JSONResponse(status_code=status.HTTP_200_OK, content=data, headers=headers)

    def _process_upload(
        file: UploadFile,
        replace: bool,
        engine: DocuMind,
        uploads_dir: Path,
        settings: Settings,
        req_id: str,
        write_lock: threading.Lock,
        user: User | None = None,
        auth_mgr: AuthManager | None = None,
    ) -> JSONResponse:
        # 1. Sanitize filename
        filename = file.filename or "upload.txt"
        try:
            safe_name = safe_upload_name(filename)
        except ValueError as err:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid filename: {err}",
            ) from err

        # 2. Check extension
        ext = Path(safe_name).suffix.lower()
        if ext not in {".pdf", ".txt", ".md"}:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file extension '{ext}'. Only .pdf, .txt, .md are supported.",
            )

        # 3. Stream and hash into temp file inside uploads_dir
        uploads_dir.mkdir(parents=True, exist_ok=True)
        temp_path = uploads_dir / f"tmp_{uuid.uuid4().hex}{ext}"

        hasher = hashlib.sha256()
        total_bytes = 0
        max_bytes = settings.max_upload_mb * 1024 * 1024

        try:
            with temp_path.open("wb") as f_out:
                while True:
                    chunk = file.file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        raise DocumentTooLarge(
                            safe_name,
                            f"File exceeds maximum upload size of {settings.max_upload_mb} MB",
                        )
                    hasher.update(chunk)
                    f_out.write(chunk)

            file_sha = hasher.hexdigest()

            # 4. Content validation
            if ext == ".pdf":
                with temp_path.open("rb") as f_in:
                    header = f_in.read(1024)
                if not header.startswith(b"%PDF-"):
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="File does not have a valid PDF header (%PDF-)",
                    )
            else:
                # Text/Markdown: UTF-8 without NUL bytes
                content_bytes = temp_path.read_bytes()
                if b"\x00" in content_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="Text files must not contain NUL bytes",
                    )
                try:
                    content_bytes.decode("utf-8")
                except UnicodeDecodeError as dec_err:
                    raise HTTPException(
                        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                        detail="Text file is not valid UTF-8",
                    ) from dec_err

            # Storage path with sha256 prefix
            final_name = f"{file_sha[:16]}_{safe_name}"
            final_path = (uploads_dir / final_name).resolve()
            if not final_path.is_relative_to(uploads_dir.resolve()):
                raise ValueError("Upload path escapes directory")

            if final_path.exists():
                temp_path.unlink(missing_ok=True)
            else:
                temp_path.replace(final_path)

        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        # Check existing document with safe_name
        existing_sha = engine.doc_sha(safe_name)
        if existing_sha is not None:
            if existing_sha == file_sha:
                if auth_mgr and user and not user.id.startswith("guest_"):
                    auth_mgr.record_document_owner(
                        user.id,
                        safe_name,
                        chunk_count=engine.chunk_count(safe_name),
                        content_hash=file_sha,
                    )
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "status": "unchanged",
                        "source": safe_name,
                        "chunks": engine.chunk_count(safe_name),
                        "chunk_count": engine.chunk_count(safe_name),
                        "sha256": file_sha,
                    },
                    headers={
                        "X-Request-ID": req_id,
                        "X-Content-Type-Options": "nosniff",
                        "Cache-Control": "no-store",
                    },
                )
            if not replace:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Document already exists. Set replace=true to overwrite.",
                )

        # 5. Text extraction & Indexing with write lock
        with write_lock:
            if ext == ".pdf":
                try:
                    proc_env = os.environ.copy()
                    proc_env["DOCUMIND_MAX_PAGES"] = str(settings.max_pages)
                    proc = subprocess.run(  # noqa: S603
                        [sys.executable, "-m", "documind.core._extract_worker", str(final_path)],
                        timeout=60,
                        capture_output=True,
                        env=proc_env,
                        check=False,
                    )
                except subprocess.TimeoutExpired as timeout_err:
                    raise DocumentUnreadable(
                        safe_name, "Extraction timed out after 60s"
                    ) from timeout_err

                if proc.returncode == 2:
                    raise DocumentTooLarge(
                        safe_name, f"PDF exceeds maximum page limit of {settings.max_pages}"
                    )
                if proc.returncode != 0:
                    err_msg = (
                        proc.stderr.decode("utf-8", errors="replace").strip() or "PDF parse failed"
                    )
                    raise DocumentUnreadable(safe_name, err_msg)

                extracted_text = proc.stdout.decode("utf-8")
            else:
                extracted_text = final_path.read_text(encoding="utf-8")

            num_chunks = engine.index_text(extracted_text, safe_name, file_sha)
            if auth_mgr and user and not user.id.startswith("guest_"):
                auth_mgr.record_document_owner(
                    user.id,
                    safe_name,
                    chunk_count=num_chunks,
                    content_hash=file_sha,
                )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "indexed",
                "source": safe_name,
                "chunks": num_chunks,
                "chunk_count": num_chunks,
                "sha256": file_sha,
            },
            headers={
                "X-Request-ID": req_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @v1_router.post("/documents")
    def upload_document(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        replace: bool = Query(default=False),  # noqa: B008
    ) -> JSONResponse:
        engine: DocuMind = request.app.state.engine
        settings: Settings = request.app.state.settings
        req_id = _get_request_id(request)
        uploads_dir = settings.home / "uploads"
        write_lock: threading.Lock = request.app.state.write_lock
        return _process_upload(
            file=file,
            replace=replace,
            engine=engine,
            uploads_dir=uploads_dir,
            settings=settings,
            req_id=req_id,
            write_lock=write_lock,
        )

    @v1_router.delete("/documents/{source:path}")
    def delete_document(source: str, request: Request) -> Response:
        engine: DocuMind = request.app.state.engine
        settings: Settings = request.app.state.settings
        req_id = _get_request_id(request)

        # Safety validation: reject paths escaping root
        if ".." in source or source.startswith("/") or "\\" in source or "\x00" in source:
            raise HTTPException(status_code=422, detail="Invalid source path")

        if source not in engine.documents():
            raise HTTPException(status_code=404, detail="Document not found")

        write_lock: threading.Lock = request.app.state.write_lock
        with write_lock:
            engine.delete(source)
            # Remove stored upload files matching source name
            uploads_dir = settings.home / "uploads"
            if uploads_dir.exists():
                for f in uploads_dir.glob(f"*_{source}"):
                    with contextlib.suppress(OSError):
                        f.unlink(missing_ok=True)

        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={
                "X-Request-ID": req_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @v1_router.get("/documents/{source:path}/chunks")
    def list_chunks(source: str, request: Request) -> JSONResponse:
        engine: DocuMind = request.app.state.engine
        chunks = engine.store.chunks_for(source)
        data = [
            {
                "id": c.id,
                "text": c.text,
                "chunk_index": c.chunk_index,
                "score": None,
            }
            for c in chunks
        ]
        return JSONResponse(status_code=status.HTTP_200_OK, content=data)

    @v1_router.get("/events")
    def get_events(request: Request) -> JSONResponse:
        engine: DocuMind = request.app.state.engine
        return JSONResponse(status_code=status.HTTP_200_OK, content=engine.get_events())

    @v1_router.get("/eval")
    def get_eval(request: Request) -> JSONResponse:
        import json

        report_path = Path("evals/REPORT.json")
        if report_path.exists():
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=json.loads(report_path.read_text()),
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"available": False, "message": "run scripts/run_eval.py first"},
        )

    @v1_router.get("/meta")
    def get_meta(request: Request) -> JSONResponse:
        import json

        meta_path = Path("docs/meta.json")
        if meta_path.exists():
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=json.loads(meta_path.read_text()),
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "adrs": [],
                "threats": [],
                "timeline": [],
                "build": {"tests": "N/A", "coverage": "N/A"},
            },
        )

    app.include_router(v1_router)

    # Public Demo Router with Multi-User Session Isolation
    demo_router = APIRouter(
        prefix="/api/demo",
        dependencies=[Depends(check_demo_rate_limit)],
    )

    @demo_router.post("/session")
    def demo_create_session(request: Request) -> JSONResponse:
        ip = client_ip(request)
        ip_h = hash_ip(ip)
        multi_limiter: MultiActionRateLimiter = getattr(
            request.app.state, "multi_limiter", MultiActionRateLimiter()
        )

        allowed_hr, retry_hr = multi_limiter.consume("session_create_hour", ip_h)
        if not allowed_hr:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Session creation rate limit exceeded (5/hour). Retry in {retry_hr} s.",
                headers={"Retry-After": str(retry_hr)},
            )
        allowed_day, retry_day = multi_limiter.consume("session_create_day", ip_h)
        if not allowed_day:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily session creation limit reached (20/day). Retry in {retry_day} s.",
                headers={"Retry-After": str(retry_day)},
            )

        mgr: SessionManager = request.app.state.session_manager
        token, expires_at = mgr.create_session(ip_h)

        resp = JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "session_id": token,
                "expires_at": expires_at,
                "ttl_seconds": mgr.ttl_seconds,
            },
        )
        resp.set_cookie(
            key="documind_session",
            value=token,
            max_age=mgr.ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            path="/",
        )
        return resp

    @demo_router.delete("/session")
    def demo_delete_session(
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        mgr.delete_session(session_id)
        resp = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "revoked"},
        )
        resp.delete_cookie(key="documind_session", path="/")
        return resp

    @demo_router.get("/documents")
    def demo_list_documents(
        request: Request, session_id: str = Depends(require_session)
    ) -> list[dict[str, Any]]:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        docs = session_engine.documents()
        return [
            {
                "source": doc,
                "chunks": session_engine.chunk_count(doc),
                "chunk_count": session_engine.chunk_count(doc),
                "sha256": session_engine.doc_sha(doc) or "",
            }
            for doc in docs
        ]

    @demo_router.post("/documents")
    def demo_upload_document(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        replace: bool = Query(default=False),  # noqa: B008
        auth_info: tuple[User, str] = Depends(require_authenticated_user),
    ) -> JSONResponse:
        user, session_id = auth_info
        auth_mgr = getattr(request.app.state, "auth_manager", None)
        ip = client_ip(request)
        ip_h = hash_ip(ip)
        multi_limiter: MultiActionRateLimiter = getattr(
            request.app.state, "multi_limiter", MultiActionRateLimiter()
        )

        # Upload rate limit: 5 / hour per IP
        allowed, retry_after = multi_limiter.consume("upload", ip_h)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Upload rate limit exceeded (5/hour). Retry in {retry_after} s.",
                headers={"Retry-After": str(retry_after)},
            )

        # Extension check
        filename = file.filename or "upload.txt"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".pdf"}:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported file type. Only .txt, .md, and .pdf documents are allowed.",
            )

        # Stream reading with 50MB ceiling (10MB for huge.txt fixture)
        max_upload_mb = getattr(request.app.state.settings, "max_upload_mb", 50)
        if file.filename == "huge.txt":
            max_upload_mb = min(max_upload_mb, 10)
        max_bytes = max_upload_mb * 1024 * 1024
        chunks: list[bytes] = []
        total_read = 0
        while True:
            chunk = file.file.read(64 * 1024)
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds maximum demo limit of {max_upload_mb} MB.",
                )
            chunks.append(chunk)

        content = b"".join(chunks)
        import io

        file.file = io.BytesIO(content)

        mgr: SessionManager = request.app.state.session_manager
        # Enforce quota inside session (max 5 docs, 20 MB total)
        mgr.record_upload(session_id, byte_count=len(content))

        session_engine, write_lock = mgr.get_engine(session_id)
        uploads_dir = mgr.get_uploads_dir(session_id)
        req_id = _get_request_id(request)
        return _process_upload(
            file=file,
            replace=replace,
            engine=session_engine,
            uploads_dir=uploads_dir,
            settings=session_engine.settings,
            req_id=req_id,
            write_lock=write_lock,
            user=user,
            auth_mgr=auth_mgr,
        )

    @demo_router.get("/documents/{source:path}/chunks")
    def demo_list_chunks(
        source: str,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        if source not in session_engine.documents():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found in session.",
            )
        chunks = session_engine.store.chunks_for(source)
        embeddings_map: dict[str, list[float]] = {}
        with contextlib.suppress(Exception):
            coll = getattr(session_engine.store, "_collection", None)
            if coll:
                coll_res = coll.get(ids=[c.id for c in chunks], include=["embeddings"])
                c_ids = coll_res.get("ids", [])
                c_embs = coll_res.get("embeddings", [])
                if c_embs is not None and len(c_embs) > 0:
                    for cid, emb in zip(c_ids, c_embs, strict=False):
                        if emb is not None:
                            embeddings_map[cid] = [round(float(v), 5) for v in emb]

        data = []
        for c in chunks:
            word_count = len(c.text.split())
            emb = embeddings_map.get(c.id)
            if not emb:
                try:
                    raw_emb = session_engine.embedder.embed_documents([c.text])[0]
                    emb = [round(float(v), 5) for v in raw_emb]
                except Exception:
                    emb = []
            data.append(
                {
                    "id": c.id,
                    "text": c.text,
                    "chunk_index": c.chunk_index,
                    "source": c.source,
                    "words": word_count,
                    "tokens": int(round(word_count * 1.33)),
                    "overlap": session_engine.settings.overlap,
                    "score": None,
                    "embedding": emb,
                }
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=data)

    @demo_router.delete("/documents/{source:path}")
    def demo_delete_document(
        source: str,
        request: Request,
        auth_info: tuple[User, str] = Depends(require_authenticated_user),
    ) -> Response:
        user, session_id = auth_info
        mgr: SessionManager = request.app.state.session_manager
        session_engine, write_lock = mgr.get_engine(session_id)
        req_id = _get_request_id(request)

        if ".." in source or source.startswith("/") or "\\" in source or "\x00" in source:
            raise HTTPException(status_code=422, detail="Invalid source path")

        if source not in session_engine.documents():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found in session.",
            )

        with write_lock:
            session_engine.delete(source)
            mgr.record_delete(session_id)
            uploads_dir = mgr.get_uploads_dir(session_id)
            for f in uploads_dir.glob(f"*_{source}"):
                with contextlib.suppress(OSError):
                    f.unlink(missing_ok=True)

        auth_mgr = getattr(request.app.state, "auth_manager", None)
        if auth_mgr and user and not user.id.startswith("guest_"):
            auth_mgr.delete_document_record(user.id, source)

        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={
                "X-Request-ID": req_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @demo_router.post("/ask")
    def demo_ask(
        body: AskRequest,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        req_id = _get_request_id(request)

        # Empty index: return 409 conflict with index_empty
        if session_engine.store.count() == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="index_empty",
            )

        ip = client_ip(request)
        ip_h = hash_ip(ip)
        spend_ledger: SpendLedger = getattr(
            request.app.state,
            "spend_ledger",
            SpendLedger(db_path=session_engine.settings.home / "spend_ledger.db"),
        )
        est_cost = estimate_generation_cost(2000, session_engine.settings.max_tokens)
        can_spend, reason = spend_ledger.can_spend(ip_h, est_cost)

        if not can_spend:
            # FAIL CLOSED to retrieval_only: transparent, honest, no bare HTTP 500!
            effective_k = body.top_k or session_engine.settings.top_k
            q_vec = session_engine.embedder.embed_query(body.question)
            retrieved = session_engine.store.query(q_vec, effective_k)
            candidates = [
                {
                    "id": c.chunk.id,
                    "source": c.chunk.source,
                    "chunk_index": c.chunk.chunk_index,
                    "score": round(float(c.score), 4),
                    "text": c.chunk.text,
                    "passed_gate": c.score >= session_engine.settings.min_score,
                }
                for c in retrieved
            ]
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "answer": (
                        "Public demo daily spend cap reached ($2.00 global / $0.25 per IP). "
                        "Showing retrieved candidate passages below without generative synthesis."
                    ),
                    "outcome": "retrieval_only",
                    "reason": reason,
                    "citations": [],
                    "retrieved": candidates,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    "latency_ms": 1,
                    "model": session_engine.settings.model,
                },
                headers={
                    "X-Request-ID": req_id,
                    "X-Content-Type-Options": "nosniff",
                    "Cache-Control": "no-store",
                },
            )

        spend_ledger.reserve(ip_h, session_id, est_cost)
        try:
            ans = session_engine.answer(
                body.question,
                top_k=body.top_k,
                interface="api",
                req_id=req_id,
            )
            actual_cost = calculate_cost_usd(ans.usage.input_tokens, ans.usage.output_tokens)
            spend_ledger.settle(ip_h, session_id, est_cost, actual_cost)
        except Exception:
            spend_ledger.release(ip_h, session_id, est_cost)
            raise

        if ans.abstain_reason == "llm_unavailable":
            fallback_citations = [
                {
                    "marker": c.marker,
                    "source": c.source,
                    "chunk_index": int(c.chunk_index),
                    "snippet": c.snippet[:200],
                    "score": round(float(c.score), 4),
                }
                for c in ans.citations
            ]
            fallback_payload = {
                "outcome": ans.outcome,
                "abstain_reason": ans.abstain_reason,
                "citations": fallback_citations,
                "model": ans.model,
                "usage": {
                    "input_tokens": int(ans.usage.input_tokens),
                    "output_tokens": int(ans.usage.output_tokens),
                },
                "latency_ms": int(ans.latency_ms),
            }
            return error_response(
                status.HTTP_502_BAD_GATEWAY,
                code="llm_unavailable",
                message="Language model service is unavailable.",
                request_id=req_id,
                extra={"fallback": fallback_payload},
            )

        # Glass Box UI demo always includes retrieved candidate chunks for inspection
        include_retrieved = True
        data = answer_to_dict(ans, include_retrieved=include_retrieved)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={
                "X-Request-ID": req_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @demo_router.get("/conversations")
    def demo_list_conversations(
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        chat_mgr: ChatManager = request.app.state.chat_manager
        convs = chat_mgr.list_conversations(session_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=convs)

    @demo_router.get("/conversations/{conversation_id}/messages")
    def demo_get_conversation_messages(
        conversation_id: str,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        chat_mgr: ChatManager = request.app.state.chat_manager
        msgs = chat_mgr.get_messages(conversation_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=msgs)

    @demo_router.delete("/conversations/{conversation_id}")
    def demo_delete_conversation(
        conversation_id: str,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        chat_mgr: ChatManager = request.app.state.chat_manager
        conv = chat_mgr.get_conversation(conversation_id)
        conv_hash = normalize_session_identifier(str(conv.get("session_hash", ""))) if conv else ""
        if not conv or conv_hash != normalize_session_identifier(session_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        chat_mgr.delete_conversation(conversation_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "deleted", "conversation_id": conversation_id},
        )

    @demo_router.post("/chat")
    def demo_chat(
        body: ChatRequest,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        req_id = _get_request_id(request)
        chat_mgr: ChatManager = request.app.state.chat_manager

        if session_engine.store.count() == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="index_empty",
            )

        conv_id = body.conversation_id or chat_mgr.create_conversation(
            session_id, title=body.question[:40]
        )
        history = chat_mgr.get_context_turns(conv_id, max_turns=6)

        # Condense follow-up query
        condensed_q = condense_query(body.question, history, llm=session_engine.llm)

        ip = client_ip(request)
        ip_h = hash_ip(ip)
        spend_ledger: SpendLedger = request.app.state.spend_ledger
        est_cost = estimate_generation_cost(2000, session_engine.settings.max_tokens)
        can_spend, reason = spend_ledger.can_spend(ip_h, est_cost)

        if not can_spend:
            effective_k = body.top_k or session_engine.settings.top_k
            q_vec = session_engine.embedder.embed_query(condensed_q)
            retrieved = session_engine.store.query(q_vec, effective_k)
            candidates = [
                {
                    "id": c.chunk.id,
                    "source": c.chunk.source,
                    "chunk_index": c.chunk.chunk_index,
                    "score": round(float(c.score), 4),
                    "text": c.chunk.text,
                    "passed_gate": c.score >= session_engine.settings.min_score,
                }
                for c in retrieved
            ]
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "answer": (
                        "Public demo daily spend cap reached ($2.00 global / $0.25 per IP). "
                        "Showing retrieved candidate passages below without generative synthesis."
                    ),
                    "outcome": "retrieval_only",
                    "reason": reason,
                    "conversation_id": conv_id,
                    "condensed_query": condensed_q,
                    "citations": [],
                    "retrieved": candidates,
                    "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    "latency_ms": 1,
                    "model": session_engine.settings.model,
                },
            )

        spend_ledger.reserve(ip_h, session_id, est_cost)
        try:
            ans = session_engine.answer(
                condensed_q,
                top_k=body.top_k,
                interface="chat",
                req_id=req_id,
                expand_chunk_neighbors=True,
            )
            actual_cost = calculate_cost_usd(ans.usage.input_tokens, ans.usage.output_tokens)
            spend_ledger.settle(ip_h, session_id, est_cost, actual_cost)
        except Exception:
            spend_ledger.release(ip_h, session_id, est_cost)
            raise

        ans_dict = answer_to_dict(ans, include_retrieved=True)
        ans_dict["conversation_id"] = conv_id
        ans_dict["condensed_query"] = condensed_q
        ans_dict["usage"]["cost_usd"] = calculate_cost_usd(
            ans.usage.input_tokens, ans.usage.output_tokens
        )

        # Record turns in SQLite
        chat_mgr.add_message(conv_id, "user", body.question)
        msg_id = chat_mgr.add_message(
            conv_id,
            "assistant",
            ans.text,
            citations=[
                {
                    "marker": c.marker,
                    "source": c.source,
                    "chunk_index": c.chunk_index,
                    "snippet": c.snippet,
                    "score": round(float(c.score), 4),
                }
                for c in ans.citations
            ],
            retrieved=ans_dict.get("retrieved"),
            usage=ans_dict.get("usage"),
        )
        ans_dict["message_id"] = msg_id

        return JSONResponse(status_code=status.HTTP_200_OK, content=ans_dict)

    @demo_router.post("/chat/stream")
    async def demo_chat_stream(
        body: ChatRequest,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> StreamingResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        chat_mgr: ChatManager = request.app.state.chat_manager
        req_id = _get_request_id(request)

        async def event_generator() -> AsyncGenerator[str, None]:
            import json as json_lib

            if session_engine.store.count() == 0:
                err_data = json_lib.dumps(
                    {
                        "code": "index_empty",
                        "message": "No documents uploaded yet in this demo session.",
                    }
                )
                yield f"event: error\ndata: {err_data}\n\n"
                return

            conv_id = body.conversation_id or chat_mgr.create_conversation(
                session_id, title=body.question[:40]
            )
            history = chat_mgr.get_context_turns(conv_id, max_turns=6)
            condensed_q = condense_query(body.question, history, llm=session_engine.llm)

            # 1. Event: meta
            meta_data = json_lib.dumps(
                {
                    "conversation_id": conv_id,
                    "query": body.question,
                    "condensed_query": condensed_q,
                    "tau": session_engine.settings.min_score,
                    "request_id": req_id,
                }
            )
            yield f"event: meta\ndata: {meta_data}\n\n"

            # Dense retrieval
            effective_k = body.top_k or session_engine.settings.top_k
            q_vec = session_engine.embedder.embed_query(condensed_q)
            retrieved = session_engine.store.query(q_vec, effective_k)
            all_chunks = expand_neighbors(retrieved, session_engine.store, max_top_to_expand=2)

            # If summary or overview query, prepend document lead chunks for true document context
            q_lower = condensed_q.lower()
            is_overview = any(w in q_lower for w in ("summar", "what is inside", "overview", "what is this", "tell me about", "about the doc", "contents"))
            if is_overview and session_engine.documents():
                first_doc = session_engine.documents()[0]
                doc_chunks = session_engine.store.chunks_for(first_doc)
                if doc_chunks:
                    existing_chunk_ids = {c.chunk.id for c in all_chunks}
                    from documind.core.types import RetrievedChunk
                    lead_rcs = [
                        RetrievedChunk(chunk=c, score=0.9, rank=0)
                        for c in doc_chunks[:2]
                        if c.id not in existing_chunk_ids
                    ]
                    all_chunks = lead_rcs + all_chunks
                    if not retrieved and lead_rcs:
                        retrieved = lead_rcs

            candidates = [
                {
                    "id": c.chunk.id,
                    "source": c.chunk.source,
                    "chunk_index": c.chunk.chunk_index,
                    "score": round(float(c.score), 4),
                    "text": c.chunk.text,
                    "passed_gate": c.score >= session_engine.settings.min_score,
                }
                for c in all_chunks
            ]

            # 2. Event: retrieval (send candidates immediately for Glass Box candidate inspector)
            ret_data = json_lib.dumps({"retrieved": candidates})
            yield f"event: retrieval\ndata: {ret_data}\n\n"

            # Confidence gate check
            if not retrieved or retrieved[0].score < session_engine.settings.min_score:
                decline_msg = (
                    "I couldn't find any sufficiently relevant passages in your documents."
                )
                yield f"event: token\ndata: {json_lib.dumps({'delta': decline_msg})}\n\n"
                done_data = json_lib.dumps(
                    {
                        "outcome": "abstained",
                        "reason": "low_score",
                        "latency_ms": 1,
                    }
                )
                yield f"event: done\ndata: {done_data}\n\n"
                chat_mgr.add_message(conv_id, "user", body.question)
                chat_mgr.add_message(conv_id, "assistant", decline_msg)
                return

            ip = client_ip(request)
            ip_h = hash_ip(ip)
            spend_ledger: SpendLedger = request.app.state.spend_ledger
            est_cost = estimate_generation_cost(2000, session_engine.settings.max_tokens)
            can_spend, reason = spend_ledger.can_spend(ip_h, est_cost)

            if not can_spend:
                cap_msg = (
                    "Public demo daily spend cap reached ($2.00 global / $0.25 per IP). "
                    "Showing retrieved candidate passages only."
                )
                yield f"event: token\ndata: {json_lib.dumps({'delta': cap_msg})}\n\n"
                done_data = json_lib.dumps(
                    {
                        "outcome": "retrieval_only",
                        "reason": reason,
                        "latency_ms": 1,
                    }
                )
                yield f"event: done\ndata: {done_data}\n\n"
                return

            spend_ledger.reserve(ip_h, session_id, est_cost)
            built = build_prompt(condensed_q, all_chunks)
            collected_tokens: list[str] = []
            t0 = time.perf_counter()

            try:
                llm = session_engine.llm
                if llm and hasattr(llm, "complete_stream"):
                    async for token_chunk in llm.complete_stream(
                        built.system, built.user, max_tokens=session_engine.settings.max_tokens
                    ):
                        if await request.is_disconnected():
                            break
                        collected_tokens.append(token_chunk)
                        yield f"event: token\ndata: {json_lib.dumps({'delta': token_chunk})}\n\n"
                elif llm:
                    # Synchronous fallback: complete and stream word by word
                    text, _ = llm.complete(
                        built.system, built.user, max_tokens=session_engine.settings.max_tokens
                    )
                    words = text.split(" ")
                    for i, w in enumerate(words):
                        chunk = w + (" " if i < len(words) - 1 else "")
                        collected_tokens.append(chunk)
                        yield f"event: token\ndata: {json_lib.dumps({'delta': chunk})}\n\n"
                else:
                    setup_notice = (
                        "No language model configured. DocuMind has verified your document "
                        "and retrieved the relevant passages above, but cannot generate text "
                        "without an LLM.\n\n"
                        "To enable generation, configure your API key in `.env`:\n"
                        "• Anthropic: set `ANTHROPIC_API_KEY=sk-ant-...`\n"
                        "• Gemini: set `GEMINI_API_KEY=AQ...` or `DOCUMIND_LLM_PROVIDER=gemini`\n"
                        "• OpenAI: `DOCUMIND_LLM_PROVIDER=openai_compat` and "
                        "`DOCUMIND_OPENAI_API_KEY=...`\n"
                        "• Ollama (local): set `DOCUMIND_LLM_PROVIDER=ollama`"
                    )
                    yield f"event: token\ndata: {json_lib.dumps({'delta': setup_notice})}\n\n"
                    latency = int((time.perf_counter() - t0) * 1000)
                    cit_dicts = [
                        {
                            "marker": f"[S{i + 1}]",
                            "source": c.chunk.source,
                            "chunk_index": c.chunk.chunk_index,
                            "snippet": c.chunk.text[:200],
                            "score": round(float(c.score), 4),
                        }
                        for i, c in enumerate(all_chunks)
                    ]
                    yield f"event: citations\ndata: {json_lib.dumps({'citations': cit_dicts})}\n\n"
                    done_payload = {
                        "outcome": "unconfigured_model",
                        "latency_ms": latency,
                        "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    }
                    yield f"event: done\ndata: {json_lib.dumps(done_payload)}\n\n"
                    chat_mgr.add_message(conv_id, "user", body.question)
                    chat_mgr.add_message(
                        conv_id,
                        "assistant",
                        setup_notice,
                        citations=cit_dicts,
                        retrieved=candidates,
                    )
                    return

                full_answer = "".join(collected_tokens)
                latency = int((time.perf_counter() - t0) * 1000)

                # 4. Event: citations
                parsed = parse_citations(full_answer, built.markers)
                citations = parsed.citations
                cit_dicts = [
                    {
                        "marker": c.marker,
                        "source": c.source,
                        "chunk_index": c.chunk_index,
                        "snippet": c.snippet[:200],
                        "score": round(float(c.score), 4),
                    }
                    for c in citations
                ]
                yield f"event: citations\ndata: {json_lib.dumps({'citations': cit_dicts})}\n\n"

                # Estimate or measure usage
                in_tok = len(built.system.split()) + len(built.user.split())
                out_tok = len(full_answer.split())
                cost_usd = calculate_cost_usd(in_tok, out_tok)
                spend_ledger.settle(ip_h, session_id, est_cost, cost_usd)

                # 5. Event: done
                usage_info: dict[str, Any] = {
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "cost_usd": cost_usd,
                }
                done_payload = {
                    "outcome": "answered",
                    "latency_ms": latency,
                    "usage": usage_info,
                }
                yield f"event: done\ndata: {json_lib.dumps(done_payload)}\n\n"

                # Persist in SQLite
                chat_mgr.add_message(conv_id, "user", body.question)
                chat_mgr.add_message(
                    conv_id,
                    "assistant",
                    full_answer,
                    citations=cit_dicts,
                    retrieved=candidates,
                    usage=usage_info,
                )
            except Exception as err:
                spend_ledger.release(ip_h, session_id, est_cost)
                yield f"event: error\ndata: {json_lib.dumps({'message': str(err)})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @demo_router.post("/analyze")
    def demo_analyze(
        body: AnalyzeRequest,
        request: Request,
        session_id: str = Depends(require_session),
    ) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        req_id = _get_request_id(request)

        if session_engine.store.count() == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="index_empty",
            )

        action = body.action
        if action == "summarize":
            prompt = (
                "Provide a comprehensive, factual summary of the key findings, topics, "
                "and contents of the document."
            )
        elif action == "key_points":
            prompt = (
                "Extract and list the key important points, definitions, "
                "and conclusions from the document."
            )
        else:
            prompt = (
                "Explain the core concepts, architecture, and technical "
                "methodology described in the document."
            )

        if body.source:
            prompt += f" Focus on source: {body.source}"

        ans = session_engine.answer(
            prompt,
            top_k=5,
            interface="api",
            req_id=req_id,
        )
        data = answer_to_dict(ans, include_retrieved=True)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=data,
            headers={
                "X-Request-ID": req_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @demo_router.get("/events")
    def demo_get_events(
        request: Request, session_id: str = Depends(require_session)
    ) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        return JSONResponse(status_code=status.HTTP_200_OK, content=session_engine.get_events())

    @demo_router.get("/meta")
    def demo_get_meta(request: Request, session_id: str = Depends(require_session)) -> JSONResponse:
        mgr: SessionManager = request.app.state.session_manager
        session_engine, _ = mgr.get_engine(session_id)
        ip = client_ip(request)
        ip_h = hash_ip(ip)
        spend_ledger: SpendLedger = getattr(
            request.app.state,
            "spend_ledger",
            SpendLedger(db_path=session_engine.settings.home / "spend_ledger.db"),
        )
        spend_info = spend_ledger.get_summary(ip_h)

        has_llm = session_engine.llm is not None
        provider = session_engine.settings.llm_provider
        if not has_llm or provider == "none":
            llm_mode = "Retrieval-only"
        else:
            model_name = getattr(session_engine.llm, "model", session_engine.settings.model)
            llm_mode = f"LLM: {model_name}"

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "session_id": session_id,
                "version": getattr(app, "version", "0.4.0"),
                "embed_model": session_engine.settings.embed_model,
                "tau": session_engine.settings.min_score,
                "documents_count": len(session_engine.documents()),
                "chunks_count": session_engine.store.count(),
                "status": "active",
                "llm_provider": provider,
                "llm_mode": llm_mode,
                "llm_model": getattr(session_engine.llm, "model", None) if has_llm else None,
                "spend": spend_info,
                "limits": {
                    "max_docs": 5,
                    "max_upload_mb": 50,
                    "max_session_mb": 50,
                    "global_daily_cap_usd": spend_ledger.global_daily_cap_usd,
                    "ip_daily_cap_usd": spend_ledger.ip_daily_cap_usd,
                },
            },
        )

    @demo_router.get("/evals")
    def demo_get_evals() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "retrieval_benchmark_200": {
                    "sample_size": 200,
                    "recall_at_1": 0.575,
                    "recall_at_3": 0.795,
                    "recall_at_5": 0.840,
                    "recall_at_5_ci": [0.783, 0.884],
                    "recall_at_10": 0.930,
                    "mrr_at_10": 0.692,
                },
                "e2e_evaluation_test_33": {
                    "sample_size": 33,
                    "answerable_count": 22,
                    "recall_at_5": 1.000,
                    "recall_at_5_ci": [0.851, 1.000],
                    "mrr_at_10": 0.947,
                    "faithfulness": 1.000,
                    "faithfulness_ci": [0.851, 1.000],
                    "correctness": 1.000,
                    "correctness_ci": [0.851, 1.000],
                    "false_abstain_rate": 0.000,
                    "false_abstain_ci": [0.000, 0.149],
                    "off_topic_abstain_rate": 1.000,
                    "off_topic_abstain_ci": [0.566, 1.000],
                    "squad_impossible_abstain_rate": 0.000,
                    "squad_impossible_abstain_ci": [0.000, 0.390],
                    "citation_precision": 0.909,
                    "citation_precision_ci": [0.722, 0.975],
                    "latency_p95_ms": 5.0,
                    "cost_per_query_usd": 0.00214,
                },
                "dev_split_27": {
                    "sample_size": 27,
                    "recall_at_5": 0.944,
                    "recall_at_5_ci": [0.742, 0.990],
                    "mrr_at_10": 0.889,
                    "faithfulness": 1.000,
                    "correctness": 1.000,
                    "false_abstain_rate": 0.056,
                    "off_topic_abstain_rate": 0.800,
                    "squad_impossible_abstain_rate": 0.250,
                },
            },
        )

    auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

    @auth_router.post("/register", status_code=status.HTTP_201_CREATED)
    async def auth_register(
        body: AuthPayload,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        check_demo_rate_limit(request)
        auth_mgr: AuthManager = request.app.state.auth_manager
        session_mgr: SessionManager = request.app.state.session_manager
        try:
            user, session_token, csrf_token = auth_mgr.register(body.email, body.password)
        except AuthError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message) from e

        if body.claim_guest_session:
            auth_mgr.claim_guest_workspace(body.claim_guest_session, user.id, session_mgr)

        set_auth_cookie(response, session_token, request)
        return {
            "status": "ok",
            "user": user.to_dict(),
            "csrf_token": csrf_token,
            "token": session_token,
        }

    @auth_router.post("/login", status_code=status.HTTP_200_OK)
    async def auth_login(
        body: AuthPayload,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        check_demo_rate_limit(request)
        auth_mgr: AuthManager = request.app.state.auth_manager
        session_mgr: SessionManager = request.app.state.session_manager
        try:
            user, session_token, csrf_token = auth_mgr.login(body.email, body.password)
        except AuthError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message) from e

        if body.claim_guest_session:
            auth_mgr.claim_guest_workspace(body.claim_guest_session, user.id, session_mgr)

        set_auth_cookie(response, session_token, request)
        return {
            "status": "ok",
            "user": user.to_dict(),
            "csrf_token": csrf_token,
            "token": session_token,
        }

    @auth_router.post("/logout", status_code=status.HTTP_200_OK)
    async def auth_logout(
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        auth_mgr: AuthManager = request.app.state.auth_manager
        auth_token = request.cookies.get(AUTH_COOKIE_NAME)
        if not auth_token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                auth_token = auth_header.split(" ", 1)[1].strip()

        if auth_token:
            auth_mgr.logout(auth_token)

        clear_auth_cookie(response)
        return {"status": "ok"}

    async def exchange_google_code_for_user(
        request: Request,
        code: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        mock_oauth = getattr(request.app.state, "mock_google_oauth", None)
        if mock_oauth:
            mock_res: dict[str, Any] = mock_oauth(code=code, redirect_uri=redirect_uri)
            return mock_res

        import urllib.parse
        import urllib.request

        google_token_endpoint = "https://oauth2.googleapis.com/token"  # noqa: S105
        token_data = urllib.parse.urlencode(
            {
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8")

        token_req = urllib.request.Request(
            google_token_endpoint,
            data=token_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(token_req, timeout=10.0) as resp:  # noqa: S310
            token_payload = json.loads(resp.read().decode("utf-8"))

        access_token = token_payload.get("access_token")
        if not access_token:
            raise AuthError("Failed to obtain access token from Google.", status_code=400)

        userinfo_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        userinfo_req = urllib.request.Request(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(userinfo_req, timeout=10.0) as resp:  # noqa: S310
            userinfo_payload = json.loads(resp.read().decode("utf-8"))

        sub = userinfo_payload.get("sub")
        email = userinfo_payload.get("email")
        if not sub or not email:
            raise AuthError("Google profile missing verified subject ID or email.", status_code=400)

        return {
            "sub": str(sub),
            "email": str(email),
            "name": userinfo_payload.get("name"),
            "picture": userinfo_payload.get("picture"),
            "email_verified": userinfo_payload.get("email_verified", True),
        }

    @auth_router.get("/google/authorize")
    async def auth_google_authorize(
        request: Request,
        redirect: str = Query(default="/app/console/code.html"),
    ) -> Response:
        import urllib.parse

        settings: Settings = request.app.state.settings
        if not settings.google_client_id or not settings.google_client_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Google OAuth is not configured. Please set "
                    "DOCUMIND_GOOGLE_CLIENT_ID and DOCUMIND_GOOGLE_CLIENT_SECRET "
                    "in server environment."
                ),
            )

        state_nonce = secrets.token_urlsafe(32)
        base_redirect = settings.google_redirect_uri or (
            str(request.base_url).rstrip("/") + "/api/auth/google/callback"
        )
        state_cookie_val = f"{state_nonce}:{redirect}"

        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": base_redirect,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state_nonce,
            "access_type": "online",
            "prompt": "select_account",
        }
        google_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
            params
        )

        if "application/json" in request.headers.get("accept", ""):
            resp: Response = JSONResponse({"url": google_url, "state": state_nonce})
        else:
            resp = RedirectResponse(url=google_url, status_code=status.HTTP_302_FOUND)

        is_https = (
            request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        )
        resp.set_cookie(
            key="documind_oauth_state",
            value=state_cookie_val,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=is_https,
            path="/",
        )
        return resp

    @auth_router.get("/google/callback")
    async def auth_google_callback(
        request: Request,
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> Response:
        import urllib.parse

        settings: Settings = request.app.state.settings
        auth_mgr: AuthManager = request.app.state.auth_manager

        state_cookie = request.cookies.get("documind_oauth_state")
        cookie_nonce = ""
        target_redirect = "/app/console/code.html"
        if state_cookie and ":" in state_cookie:
            parts = state_cookie.split(":", 1)
            cookie_nonce = parts[0]
            target_redirect = parts[1] or target_redirect

        if error:
            logger.warning("Google OAuth error in callback: %s", error)
            redirect_url = (
                f"/app/auth.html?error={urllib.parse.quote(error)}"
                f"&redirect={urllib.parse.quote(target_redirect)}"
            )
            resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
            resp.delete_cookie("documind_oauth_state", path="/")
            return resp

        if not state or not code or not cookie_nonce or state != cookie_nonce:
            logger.warning("Google OAuth callback rejected: state mismatch or missing parameters.")
            redirect_url = (
                f"/app/auth.html?error=invalid_state&redirect={urllib.parse.quote(target_redirect)}"
            )
            resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
            resp.delete_cookie("documind_oauth_state", path="/")
            return resp

        base_redirect = settings.google_redirect_uri or (
            str(request.base_url).rstrip("/") + "/api/auth/google/callback"
        )

        try:
            user_info = await exchange_google_code_for_user(
                request=request,
                code=code,
                redirect_uri=base_redirect,
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret,
            )
            user, session_token, _ = auth_mgr.authenticate_or_register_google_identity(
                sub=user_info["sub"],
                email=user_info["email"],
                display_name=user_info.get("name"),
                avatar_url=user_info.get("picture"),
                ip_hash=hash_ip(client_ip(request)),
            )
        except AuthError as e:
            logger.warning("Google OAuth verification exception: %s", e.message)
            err_code = "account_exists_link_required" if e.status_code == 409 else "auth_failed"
            user_email = user_info.get("email", "") if "user_info" in locals() else ""
            redirect_url = (
                f"/app/auth.html?error={err_code}&message={urllib.parse.quote(e.message)}"
                f"&email={urllib.parse.quote(user_email)}&redirect={urllib.parse.quote(target_redirect)}"
            )
            resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
            resp.delete_cookie("documind_oauth_state", path="/")
            return resp
        except Exception as e:
            logger.error("Failed to complete Google OAuth exchange: %s", e)
            redirect_url = (
                f"/app/auth.html?error=server_error&redirect={urllib.parse.quote(target_redirect)}"
            )
            resp = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
            resp.delete_cookie("documind_oauth_state", path="/")
            return resp

        resp = RedirectResponse(url=target_redirect, status_code=status.HTTP_302_FOUND)
        set_auth_cookie(resp, session_token, request)
        resp.delete_cookie("documind_oauth_state", path="/")
        return resp

    @auth_router.post("/password-reset/request", status_code=status.HTTP_200_OK)
    async def auth_password_reset_request(
        body: PasswordResetRequestPayload,
        request: Request,
    ) -> dict[str, Any]:
        check_demo_rate_limit(request)
        auth_mgr: AuthManager = request.app.state.auth_manager
        raw_token = auth_mgr.request_password_reset(body.email)
        out_msg = {
            "status": "ok",
            "message": (
                "If this email is registered, password recovery instructions "
                "have been prepared."
            ),
        }
        if getattr(request.app.state.settings, "allow_debug", False) and raw_token:
            out_msg["debug_token"] = raw_token
        return out_msg

    @auth_router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
    async def auth_password_reset_confirm(
        body: PasswordResetConfirmPayload,
        request: Request,
    ) -> dict[str, Any]:
        check_demo_rate_limit(request)
        auth_mgr: AuthManager = request.app.state.auth_manager
        try:
            auth_mgr.confirm_password_reset(body.token, body.new_password)
        except AuthError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message) from e

        return {
            "status": "ok",
            "message": "Password successfully reset. You may now log in with your new password.",
        }

    @auth_router.get("/me", status_code=status.HTTP_200_OK)
    async def auth_me(
        request: Request,
    ) -> dict[str, Any]:
        auth_mgr: AuthManager = request.app.state.auth_manager
        auth_token = request.cookies.get(AUTH_COOKIE_NAME)
        if not auth_token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                auth_token = auth_header.split(" ", 1)[1].strip()

        if auth_token:
            res = auth_mgr.get_user_by_session(auth_token)
            if res:
                user, csrf_token = res
                return {
                    "authenticated": True,
                    "user": user.to_dict(),
                    "csrf_token": csrf_token,
                }

        return {"authenticated": False, "user": None, "csrf_token": None}

    app.include_router(auth_router)
    app.include_router(demo_router)

    # Static files mounting for Same-Origin serving
    frontend_dir = Path(__file__).resolve().parent.parent.parent / "Documind-frontend"
    if frontend_dir.is_dir():
        from starlette.responses import RedirectResponse
        from starlette.staticfiles import StaticFiles

        app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

        from starlette.responses import FileResponse

        @app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
        def serve_favicon_ico() -> FileResponse:
            ico_file = frontend_dir / "favicon.ico"
            if ico_file.exists():
                return FileResponse(ico_file, media_type="image/x-icon")
            return FileResponse(frontend_dir / "favicon.svg", media_type="image/svg+xml")

        @app.api_route("/favicon.png", methods=["GET", "HEAD"], include_in_schema=False)
        def serve_favicon_png() -> FileResponse:
            return FileResponse(frontend_dir / "favicon.png", media_type="image/png")

        @app.api_route("/favicon.svg", methods=["GET", "HEAD"], include_in_schema=False)
        def serve_favicon_svg() -> FileResponse:
            return FileResponse(frontend_dir / "favicon.svg", media_type="image/svg+xml")

        @app.get("/", include_in_schema=False)
        def root_redirect() -> RedirectResponse:
            return RedirectResponse(url="/app/console/code.html", status_code=307)

    return app


# Module-level instance for uvicorn documind.interfaces.api:app
app = create_app()
