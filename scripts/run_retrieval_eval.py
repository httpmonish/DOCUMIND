#!/usr/bin/env python3
"""scripts/run_retrieval_eval.py -- Benchmark retrieval performance, sweeps, and ablations."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from documind.core.chunker import chunk_document
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.eval_metrics import (
    is_gold,
    mrr_at_k,
    paired_bootstrap_ci,
    percentile,
    pick_threshold,
    recall_at_k,
    threshold_sweep,
    wilson_interval,
)
from documind.core.types import Chunk, Document
from documind.core.vector_store import ChromaStore, NumpyStore

CORPUS_DIR = Path(__file__).parent.parent / "evals" / "corpus"
RETRIEVAL_SET_FILE = Path(__file__).parent.parent / "evals" / "retrieval_set.jsonl"
IMPOSSIBLE_SET_FILE = Path(__file__).parent.parent / "evals" / "squad_impossible.jsonl"
RUNS_DIR = Path(__file__).parent.parent / "evals" / "runs"


class MiniLMEmbedderWrapper:
    """Wrapper for sentence-transformers/all-MiniLM-L6-v2 comparison (offline/local)."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_id = "sentence-transformers/all-MiniLM-L6-v2"
        self._model = SentenceTransformer(self.model_id, device="cpu")
        self.dim = int(self._model.get_sentence_embedding_dimension())
        self.max_seq_length = int(getattr(self._model, "max_seq_length", 256))

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vecs = self._model.encode(
            list(texts),
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        vec = self._model.encode(text, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)


def load_corpus() -> list[Document]:
    docs: list[Document] = []
    for md_path in sorted(CORPUS_DIR.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        docs.append(Document(source=md_path.name, text=text, sha256="sha"))
    return docs


def load_retrieval_questions() -> list[dict]:
    return [
        json.loads(line) for line in RETRIEVAL_SET_FILE.read_text(encoding="utf-8").splitlines()
    ]


def load_impossible_questions() -> list[dict]:
    if not IMPOSSIBLE_SET_FILE.exists():
        return []
    return [
        json.loads(line) for line in IMPOSSIBLE_SET_FILE.read_text(encoding="utf-8").splitlines()
    ]


def evaluate_retrieval(
    docs: list[Document],
    questions: list[dict],
    embedder,
    *,
    chunk_size: int = 200,
    overlap: int = 30,
    prefix_query: bool = True,
    store_type: str = "numpy",
    cache_dir: Path | None = None,
) -> dict:
    t_start = time.perf_counter()

    # 1. Chunk documents
    chunks: list[Chunk] = []
    for doc in docs:
        raw_chunks = chunk_document(
            {"text": doc.text, "source": doc.source},
            chunk_size=chunk_size,
            overlap=overlap,
        )
        for c in raw_chunks:
            chunks.append(
                Chunk(
                    id=c["id"],
                    text=c["text"],
                    source=doc.source,
                    chunk_index=c["chunk_index"],
                    doc_sha256="sha",
                )
            )

    # 2. Embed chunks with disk caching
    model_name = getattr(embedder, "model_id", "default").replace("/", "_")
    vec_cache = cache_dir / f"vecs_{model_name}_c{chunk_size}_o{overlap}.npy" if cache_dir else None

    if vec_cache and vec_cache.exists():
        chunk_vectors = np.load(vec_cache)
    else:
        chunk_texts = [c.text for c in chunks]
        chunk_vectors = embedder.embed_documents(chunk_texts)
        if vec_cache:
            vec_cache.parent.mkdir(parents=True, exist_ok=True)
            np.save(vec_cache, chunk_vectors)

    # 3. Index in store
    if store_type == "chroma":
        temp_chroma = (cache_dir or RUNS_DIR) / "chroma_eval"
        if temp_chroma.exists():
            shutil.rmtree(temp_chroma)
        store = ChromaStore(temp_chroma, model_name, embedder.dim)
    else:
        store = NumpyStore(dim=embedder.dim)

    store.upsert(chunks, chunk_vectors)
    index_time = time.perf_counter() - t_start

    # 4. Evaluate questions
    per_q_flags: list[list[bool]] = []
    r5_hit_vector: list[float] = []
    latencies: list[float] = []
    top1_scores: list[float] = []
    top5_chunk_ids: list[list[str]] = []
    no_gold_count = 0

    for q in questions:
        q_text = q["question"]
        t0 = time.perf_counter()

        if prefix_query and hasattr(embedder, "embed_query"):
            q_vec = embedder.embed_query(q_text)
        else:
            q_vec = embedder.embed_documents([q_text])[0]

        hits = store.query(q_vec, top_k=10)
        lat = (time.perf_counter() - t0) * 1000
        latencies.append(lat)

        top1_scores.append(hits[0].score if hits else 0.0)
        top5_chunk_ids.append([h.chunk.id for h in hits[:5]])

        gold_sources = q.get("gold_sources", [])
        gold_snippets = q.get("gold_snippets", [])

        # Check if gold exists anywhere in the index for this question
        any_gold_in_index = any(
            is_gold(c.source, c.text, gold_sources, gold_snippets) for c in chunks
        )
        if not any_gold_in_index:
            no_gold_count += 1

        flags = [is_gold(h.chunk.source, h.chunk.text, gold_sources, gold_snippets) for h in hits]
        per_q_flags.append(flags)
        r5_hit_vector.append(1.0 if any(flags[:5]) else 0.0)

    n_q = len(questions)
    r1 = recall_at_k(per_q_flags, 1)
    r3 = recall_at_k(per_q_flags, 3)
    r5 = recall_at_k(per_q_flags, 5)
    r10 = recall_at_k(per_q_flags, 10)
    mrr = mrr_at_k(per_q_flags, 10)
    wilson_r5 = wilson_interval(int(sum(r5_hit_vector)), n_q)
    lat_p50 = percentile(latencies, 50)
    lat_p95 = percentile(latencies, 95)

    return {
        "chunk_size": chunk_size,
        "overlap": overlap,
        "prefix_query": prefix_query,
        "chunks_count": len(chunks),
        "index_seconds": index_time,
        "n": n_q,
        "recall@1": r1,
        "recall@3": r3,
        "recall@5": r5,
        "recall@10": r10,
        "mrr@10": mrr,
        "wilson_r5": wilson_r5,
        "lat_p50": lat_p50,
        "lat_p95": lat_p95,
        "no_gold": no_gold_count,
        "r5_hit_vector": r5_hit_vector,
        "top1_scores": top1_scores,
        "top5_chunk_ids": top5_chunk_ids,
        "per_q_flags": per_q_flags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval benchmarks and ablations.")
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Run chunk grid, prefix, and model ablations",
    )
    args = parser.parse_args()

    docs = load_corpus()
    questions = load_retrieval_questions()
    impossible_qs = load_impossible_questions()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    cache_dir = RUNS_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    embedder = SentenceTransformerEmbedder()
    model_slug = getattr(embedder, "model_id", "default").replace("/", "_")

    print("=== DOCUMIND RETRIEVAL BENCHMARK ===")
    print(f"Corpus: {len(docs)} articles | Questions: {len(questions)} answerable\n")

    # Run baseline: 200/30, bge-small
    base = evaluate_retrieval(
        docs,
        questions,
        embedder,
        chunk_size=200,
        overlap=30,
        prefix_query=True,
        cache_dir=cache_dir,
    )

    header = (
        f"{'Config':<18} | {'Chunks':<6} | {'Idx (s)':<7} | {'R@1':<6} | "
        f"{'R@3':<6} | {'R@5':<6} | {'R@10':<6} | {'MRR@10':<7} | "
        f"{'R@5 95% CI':<15} | {'p50/p95 (ms)':<13} | {'no_gold'}"
    )
    print(header)
    print("-" * len(header))

    def print_row(name: str, res: dict) -> None:
        ci_str = f"[{res['wilson_r5'][0]:.3f}, {res['wilson_r5'][1]:.3f}]"
        lat_str = f"{res['lat_p50']:.1f} / {res['lat_p95']:.1f}"
        print(
            f"{name:<18} | {res['chunks_count']:<6} | {res['index_seconds']:<7.2f} | "
            f"{res['recall@1']:<6.3f} | {res['recall@3']:<6.3f} | {res['recall@5']:<6.3f} | "
            f"{res['recall@10']:<6.3f} | {res['mrr@10']:<7.3f} | {ci_str:<15} | "
            f"{lat_str:<13} | {res['no_gold']}"
        )

    print_row("200/30 (baseline)", base)

    # Save baseline run
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = RUNS_DIR / f"retrieval_{ts}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": ts,
                "config": {
                    "chunk_size": 200,
                    "overlap": 30,
                    "model": embedder.model_id,
                },
                "metrics": {
                    "recall@1": base["recall@1"],
                    "recall@3": base["recall@3"],
                    "recall@5": base["recall@5"],
                    "recall@10": base["recall@10"],
                    "mrr@10": base["mrr@10"],
                    "wilson_r5": base["wilson_r5"],
                    "no_gold": base["no_gold"],
                },
                "per_q_flags": base["per_q_flags"],
            },
            f,
            indent=2,
        )
    print(f"\nBaseline results saved to {out_file}")

    if not args.sweep:
        return

    print("\n=== 1. CHUNK GRID SWEEPS (3x3) ===")
    grid_configs = [
        (120, 0),
        (120, 30),
        (120, 60),
        (200, 0),
        (200, 30),
        (200, 60),
        (300, 0),
        (300, 30),
        (300, 60),
    ]

    sweep_results = []
    print(header)
    print("-" * len(header))
    for c_size, c_over in grid_configs:
        res = evaluate_retrieval(
            docs,
            questions,
            embedder,
            chunk_size=c_size,
            overlap=c_over,
            prefix_query=True,
            cache_dir=cache_dir,
        )
        sweep_results.append(((c_size, c_over), res))
        print_row(f"{c_size}/{c_over}", res)

    print("\n--- Paired Bootstrap CI vs Baseline (200/30) on Recall@5 ---")
    base_hits = base["r5_hit_vector"]
    for (c_size, c_over), res in sweep_results:
        diff, lo, hi = paired_bootstrap_ci(base_hits, res["r5_hit_vector"], n_boot=2000, seed=42)
        status = "KEEP" if (diff >= 0.05 and lo > 0) else "NO SIGNIFICANT GAIN"
        print(
            f"  {c_size:3d}/{c_over:2d}: delta = {diff:+.4f} "
            f"(95% CI: [{lo:+.4f}, {hi:+.4f}]) -> {status}"
        )

    print("\n=== 2. QUERY PREFIX ABLATION (Asymmetric Retrieval) ===")
    no_prefix_res = evaluate_retrieval(
        docs,
        questions,
        embedder,
        chunk_size=200,
        overlap=30,
        prefix_query=False,
        cache_dir=cache_dir,
    )
    print_row("200/30 (no-prefix)", no_prefix_res)
    diff, lo, hi = paired_bootstrap_ci(
        no_prefix_res["r5_hit_vector"], base_hits, n_boot=2000, seed=42
    )
    print(f"  Delta (prefix vs no-prefix): {diff:+.4f} (95% CI: [{lo:+.4f}, {hi:+.4f}])")

    print("\n=== 3. EMBEDDING MODEL COMPARISON (bge-small vs all-MiniLM-L6-v2) ===")
    try:
        minilm = MiniLMEmbedderWrapper()
        minilm_res = evaluate_retrieval(
            docs,
            questions,
            minilm,
            chunk_size=200,
            overlap=30,
            prefix_query=False,
            cache_dir=cache_dir,
        )
        print_row("all-MiniLM-L6-v2", minilm_res)
        diff, lo, hi = paired_bootstrap_ci(
            minilm_res["r5_hit_vector"], base_hits, n_boot=2000, seed=42
        )
        print(f"  Delta (bge-small vs MiniLM): {diff:+.4f} (95% CI: [{lo:+.4f}, {hi:+.4f}])")
    except Exception as err:
        print(f"  Skipping MiniLM comparison: {err}")

    print("\n=== 4. EXACT VS ANN RETRIEVAL (NumpyStore vs ChromaStore) ===")
    chroma_res = evaluate_retrieval(
        docs,
        questions,
        embedder,
        chunk_size=200,
        overlap=30,
        store_type="chroma",
        cache_dir=cache_dir,
    )
    overlaps = []
    for exact_ids, ann_ids in zip(
        base["top5_chunk_ids"], chroma_res["top5_chunk_ids"], strict=True
    ):
        common = len(set(exact_ids) & set(ann_ids))
        overlaps.append(common / 5.0)
    mean_overlap = sum(overlaps) / len(overlaps)
    print(f"  Mean Overlap@5 between NumpyStore and ChromaStore: {mean_overlap:.4f}")

    print("\n=== 5. SCORE THRESHOLD CALIBRATION (Sweep over Taus) ===")
    on_scores = base["top1_scores"]

    if impossible_qs:
        chunks_200_30 = []
        for doc in docs:
            raw_c = chunk_document(
                {"text": doc.text, "source": doc.source},
                chunk_size=200,
                overlap=30,
            )
            for c in raw_c:
                chunks_200_30.append(
                    Chunk(
                        id=c["id"],
                        text=c["text"],
                        source=doc.source,
                        chunk_index=c["chunk_index"],
                        doc_sha256="sha",
                    )
                )
        nstore = NumpyStore(dim=embedder.dim)
        nstore.upsert(chunks_200_30, np.load(cache_dir / f"vecs_{model_slug}_c200_o30.npy"))

        actual_imp_scores = []
        for q in impossible_qs:
            qv = embedder.embed_query(q["question"])
            h = nstore.query(qv, 1)
            actual_imp_scores.append(h[0].score if h else 0.0)

        taus = [round(float(t), 2) for t in np.arange(0.20, 0.85, 0.05)]
        rows = threshold_sweep(on_scores, actual_imp_scores, taus)
        best_tau = pick_threshold(rows, max_false_abstain=0.10)
        print(f"  Taus evaluated: {taus[0]} to {taus[-1]}")
        print(f"  Optimal min_score threshold on SQuAD impossible: {best_tau}")
        for r in rows:
            if r["tau"] in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
                print(
                    f"    tau={r['tau']:.2f}: false_abstain={r['false_abstain']:.3f}, "
                    f"abstain_rate={r['abstain_rate']:.3f}"
                )


if __name__ == "__main__":
    main()
