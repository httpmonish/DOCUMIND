"""documind/core/pipeline.py
The DocuMind answer engine: retrieval, abstention cascades, LLM generation, and citation validation.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from documind.core.chunker import chunk_document
from documind.core.citations import is_decline, parse_citations
from documind.core.config import Settings
from documind.core.errors import LLMAuthError, LLMUnavailable
from documind.core.ingest import IndexReport, index_path
from documind.core.logging_utils import QueryLogger
from documind.core.pricing import cost_usd
from documind.core.prompt import DECLINE_SENTINEL, PROMPT_VERSION, build_prompt
from documind.core.types import (
    LLM,
    Answer,
    Chunk,
    Citation,
    Embedder,
    RetrievedChunk,
    Usage,
    VectorStore,
)


class DocuMind:
    """Core grounded Q&A engine coordinating retrieval, LLM generation, and validation."""

    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        store: VectorStore,
        llm: LLM | None = None,
    ) -> None:
        self.settings = settings
        self.s = settings
        self.embedder = embedder
        self.store = store
        self.llm = llm
        self.logger = QueryLogger(self.settings.home / "logs" / "queries.jsonl")

    def documents(self) -> list[str]:
        """Return all distinct indexed document source paths."""
        return self.store.sources()

    def delete(self, source: str) -> int:
        """Delete all chunks for a source document."""
        return self.store.delete_source(source)

    def chunk_count(self, source: str) -> int:
        """Return the number of indexed chunks for a source document."""
        return self.store.count_for(source)

    def doc_sha(self, source: str) -> str | None:
        """Return the SHA-256 hash for an indexed document source, or None if not found."""
        return self.store.doc_sha(source)

    def index(self, path: Path | str, root: Path | str | None = None) -> IndexReport:
        """Index a file or directory into the vector store."""
        target_path = Path(path).resolve()
        if root:
            target_root = Path(root).resolve()
        else:
            target_root = target_path if target_path.is_dir() else target_path.parent
        return index_path(target_path, target_root, self.embedder, self.store, self.settings)

    def index_text(self, text: str, source: str, sha256: str) -> int:
        """Chunk, embed, and index raw document text preserving write ordering."""
        raw_chunks = chunk_document(
            {"text": text, "source": source},
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.overlap,
        )
        typed_chunks = [
            Chunk(
                id=c["id"],
                text=c["text"],
                source=source,
                chunk_index=c["chunk_index"],
                doc_sha256=sha256,
            )
            for c in raw_chunks
        ]
        if not typed_chunks:
            return 0

        vectors = self.embedder.embed_documents([c.text for c in typed_chunks])

        # Write order:
        # 1. Delete old data
        # 2. Upsert chunks 1..n
        # 3. Upsert chunk 0 last
        self.delete(source)
        write_succeeded = False
        try:
            if len(typed_chunks) > 1:
                self.store.upsert(typed_chunks[1:], vectors[1:])
            self.store.upsert(typed_chunks[:1], vectors[:1])
            write_succeeded = True
        finally:
            if not write_succeeded:
                self.delete(source)

        return len(typed_chunks)

    def search(self, question: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """Pure semantic search without LLM synthesis."""
        self._validate_input(question, top_k)
        effective_k = top_k if top_k is not None else self.settings.top_k
        if self.store.count() == 0:
            return []
        q_vec = self.embedder.embed_query(question)
        return self.store.query(q_vec, effective_k)

    def answer(
        self,
        question: str,
        *,
        top_k: int | None = None,
        interface: str = "core",
        req_id: str | None = None,
    ) -> Answer:
        """Answer a user question strictly grounded in indexed documents.

        Abstention Decision Flowchart:
        1. empty_index: store.count() == 0 -> abstain immediately without embedding or LLM.
        2. low_score: top-1 cosine score < min_score -> abstain without LLM call.
        3. no_llm: engine.llm is None -> return retrieved chunks as citations.
        4. llm_unavailable: LLM call fails (timeout/429/5xx/auth) -> fallback to retrieved chunks.
        5. model_declined: model response matches DECLINE_SENTINEL -> abstain with zero citations.
        6. uncited: model answer contains no valid [S#] citations -> fallback to retrieved chunks.
        """
        t0 = time.perf_counter()
        self._validate_input(question, top_k)
        effective_k = top_k if top_k is not None else self.settings.top_k

        req_id = req_id if req_id is not None else uuid.uuid4().hex
        q_sha = hashlib.sha256(question.encode("utf-8")).hexdigest()
        q_len = len(question)

        embed_ms = 0
        retrieve_ms = 0
        llm_ms = 0

        # Stage 1: empty_index check
        if self.store.count() == 0:
            total_ms = int((time.perf_counter() - t0) * 1000)
            ans = Answer(
                text="Your document index is empty. No documents indexed.",
                citations=(),
                outcome="abstained",
                model=self.settings.model,
                usage=Usage(0, 0),
                latency_ms=total_ms,
                retrieved=(),
                abstain_reason="empty_index",
            )
            self._log_query(
                req_id=req_id,
                interface=interface,
                q_sha=q_sha,
                q_len=q_len,
                top_k=effective_k,
                retrieved=(),
                ans=ans,
                embed_ms=0,
                retrieve_ms=0,
                llm_ms=0,
                total_ms=total_ms,
                invalid_citations=0,
                error_type=None,
                question=question,
            )
            return ans

        # Embedding query
        t_emb0 = time.perf_counter()
        q_vec = self.embedder.embed_query(question)
        embed_ms = int((time.perf_counter() - t_emb0) * 1000)

        # Retrieval
        t_ret0 = time.perf_counter()
        retrieved = self.store.query(q_vec, effective_k)
        retrieve_ms = int((time.perf_counter() - t_ret0) * 1000)

        ret_tuple = tuple(retrieved)

        # Stage 2: low_score check
        if not retrieved or retrieved[0].score < self.settings.min_score:
            total_ms = int((time.perf_counter() - t0) * 1000)
            ans = Answer(
                text="I couldn't find any sufficiently relevant passages in your documents.",
                citations=(),
                outcome="abstained",
                model=self.settings.model,
                usage=Usage(0, 0),
                latency_ms=total_ms,
                retrieved=ret_tuple,
                abstain_reason="low_score",
            )
            self._log_query(
                req_id=req_id,
                interface=interface,
                q_sha=q_sha,
                q_len=q_len,
                top_k=effective_k,
                retrieved=ret_tuple,
                ans=ans,
                embed_ms=embed_ms,
                retrieve_ms=retrieve_ms,
                llm_ms=0,
                total_ms=total_ms,
                invalid_citations=0,
                error_type=None,
                question=question,
            )
            return ans

        fallback_citations = self._make_fallback_citations(retrieved)

        # Stage 3: no_llm check
        if self.llm is None:
            total_ms = int((time.perf_counter() - t0) * 1000)
            ans = Answer(
                text="No language model is configured; returning relevant passages.",
                citations=fallback_citations,
                outcome="abstained",
                model=self.settings.model,
                usage=Usage(0, 0),
                latency_ms=total_ms,
                retrieved=ret_tuple,
                abstain_reason="no_llm",
            )
            self._log_query(
                req_id=req_id,
                interface=interface,
                q_sha=q_sha,
                q_len=q_len,
                top_k=effective_k,
                retrieved=ret_tuple,
                ans=ans,
                embed_ms=embed_ms,
                retrieve_ms=retrieve_ms,
                llm_ms=0,
                total_ms=total_ms,
                invalid_citations=0,
                error_type=None,
                question=question,
            )
            return ans

        # Build prompt
        built = build_prompt(question, retrieved)

        # Stage 4: LLM call with error catching (llm_unavailable)
        t_llm0 = time.perf_counter()
        try:
            raw_text, usage = self.llm.complete(
                built.system,
                built.user,
                max_tokens=self.settings.max_tokens,
            )
            llm_ms = int((time.perf_counter() - t_llm0) * 1000)
        except (LLMUnavailable, LLMAuthError) as err:
            llm_ms = int((time.perf_counter() - t_llm0) * 1000)
            total_ms = int((time.perf_counter() - t0) * 1000)
            error_type = type(err).__name__
            ans = Answer(
                text="The language model is currently unavailable; showing relevant passages.",
                citations=fallback_citations,
                outcome="abstained",
                model=self.settings.model,
                usage=Usage(0, 0),
                latency_ms=total_ms,
                retrieved=ret_tuple,
                abstain_reason="llm_unavailable",
            )
            self._log_query(
                req_id=req_id,
                interface=interface,
                q_sha=q_sha,
                q_len=q_len,
                top_k=effective_k,
                retrieved=ret_tuple,
                ans=ans,
                embed_ms=embed_ms,
                retrieve_ms=retrieve_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
                invalid_citations=0,
                error_type=error_type,
                question=question,
            )
            return ans

        # Stage 5: model_declined check
        if is_decline(raw_text):
            total_ms = int((time.perf_counter() - t0) * 1000)
            ans = Answer(
                text=DECLINE_SENTINEL,
                citations=(),
                outcome="abstained",
                model=self.settings.model,
                usage=usage,
                latency_ms=total_ms,
                retrieved=ret_tuple,
                abstain_reason="model_declined",
            )
            self._log_query(
                req_id=req_id,
                interface=interface,
                q_sha=q_sha,
                q_len=q_len,
                top_k=effective_k,
                retrieved=ret_tuple,
                ans=ans,
                embed_ms=embed_ms,
                retrieve_ms=retrieve_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
                invalid_citations=0,
                error_type=None,
                question=question,
            )
            return ans

        # Parse citations
        parsed = parse_citations(raw_text, built.markers)

        # Stage 6: uncited check
        if not parsed.citations:
            total_ms = int((time.perf_counter() - t0) * 1000)
            ans = Answer(
                text="The model response lacked verified citations; showing relevant passages.",
                citations=fallback_citations,
                outcome="abstained",
                model=self.settings.model,
                usage=usage,
                latency_ms=total_ms,
                retrieved=ret_tuple,
                abstain_reason="uncited",
            )
            self._log_query(
                req_id=req_id,
                interface=interface,
                q_sha=q_sha,
                q_len=q_len,
                top_k=effective_k,
                retrieved=ret_tuple,
                ans=ans,
                embed_ms=embed_ms,
                retrieve_ms=retrieve_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
                invalid_citations=parsed.invalid,
                error_type=None,
                question=question,
            )
            return ans

        # All checks passed: valid answered outcome
        total_ms = int((time.perf_counter() - t0) * 1000)
        ans = Answer(
            text=parsed.text,
            citations=parsed.citations,
            outcome="answered",
            model=self.settings.model,
            usage=usage,
            latency_ms=total_ms,
            retrieved=ret_tuple,
            abstain_reason=None,
        )
        self._log_query(
            req_id=req_id,
            interface=interface,
            q_sha=q_sha,
            q_len=q_len,
            top_k=effective_k,
            retrieved=ret_tuple,
            ans=ans,
            embed_ms=embed_ms,
            retrieve_ms=retrieve_ms,
            llm_ms=llm_ms,
            total_ms=total_ms,
            invalid_citations=parsed.invalid,
            error_type=None,
            question=question,
        )
        return ans

    def _validate_input(self, question: str, top_k: int | None) -> None:
        if not question or not question.strip():
            raise ValueError("Question cannot be empty or whitespace only")
        if len(question) > self.settings.max_question_chars:
            raise ValueError(
                f"Question exceeds max length of {self.settings.max_question_chars} chars"
            )
        if top_k is not None and (top_k < 1 or top_k > self.settings.max_top_k):
            raise ValueError(f"top_k must be between 1 and {self.settings.max_top_k}, got {top_k}")

    def _make_fallback_citations(self, retrieved: Sequence[RetrievedChunk]) -> tuple[Citation, ...]:
        return tuple(
            Citation(
                marker=f"S{i}",
                source=rc.chunk.source,
                chunk_index=rc.chunk.chunk_index,
                snippet=rc.chunk.text[:200],
                score=rc.score,
            )
            for i, rc in enumerate(retrieved, start=1)
        )

    def _log_query(
        self,
        *,
        req_id: str,
        interface: str,
        q_sha: str,
        q_len: int,
        top_k: int,
        retrieved: Sequence[RetrievedChunk],
        ans: Answer,
        embed_ms: int,
        retrieve_ms: int,
        llm_ms: int,
        total_ms: int,
        invalid_citations: int,
        error_type: str | None,
        question: str,
    ) -> None:
        ret_log = [{"id": rc.chunk.id, "score": round(float(rc.score), 4)} for rc in retrieved]
        cost = cost_usd(ans.model, ans.usage)

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": req_id,
            "interface": interface,
            "question_sha256": q_sha,
            "question_chars": q_len,
            "top_k": top_k,
            "retrieved": ret_log,
            "outcome": ans.outcome,
            "abstain_reason": ans.abstain_reason,
            "error_type": error_type,
            "embed_ms": embed_ms,
            "retrieve_ms": retrieve_ms,
            "llm_ms": llm_ms,
            "total_ms": total_ms,
            "model": ans.model,
            "input_tokens": ans.usage.input_tokens,
            "output_tokens": ans.usage.output_tokens,
            "cost_usd": cost,
            "invalid_citations": invalid_citations,
            "prompt_version": PROMPT_VERSION,
        }
        if self.settings.log_questions:
            record["question"] = question

        self.logger.write(record)
