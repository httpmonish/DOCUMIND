"""documind/interfaces/api.py
FastAPI REST API adapter for DocuMind.
Strictly decoupled: delegates all search, retrieval, and indexing to DocuMind core.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import os
import re
import subprocess
import sys
import threading
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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

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
from documind.core.serialize import answer_to_dict
from documind.interfaces.ratelimit import TokenBucketLimiter

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
    ) -> JSONResponse:
        req_id = _get_request_id(request)
        code = "http_error"
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            code = "unauthorized"
        elif exc.status_code == status.HTTP_404_NOT_FOUND:
            code = "not_found"
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
    app.state.limiter = limiter or TokenBucketLimiter(rate_per_min=app_settings.rate_limit_per_min)
    app.state.write_lock = threading.Lock()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5500", "http://127.0.0.1:5500"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Request ID and security headers middleware
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
            "tau": engine.settings.min_score if engine else 0.45,
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

    @v1_router.post("/documents")
    def upload_document(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
        replace: bool = Query(default=False),  # noqa: B008
    ) -> JSONResponse:
        engine: DocuMind = request.app.state.engine
        settings: Settings = request.app.state.settings
        req_id = _get_request_id(request)

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

        # 3. Stream and hash into temp file inside uploads/
        uploads_dir = settings.home / "uploads"
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
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "status": "unchanged",
                        "source": safe_name,
                        "chunks": engine.chunk_count(safe_name),
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
        write_lock: threading.Lock = request.app.state.write_lock
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

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={
                "status": "indexed",
                "source": safe_name,
                "chunks": num_chunks,
                "sha256": file_sha,
            },
            headers={
                "X-Request-ID": req_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
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

    return app


# Module-level instance for uvicorn documind.interfaces.api:app
app = create_app()
