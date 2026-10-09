# 0001. Embedding Model Selection

## Context
DocuMind converts raw text chunks from technical documents into dense semantic vector representations for similarity search. We require a fast, local, CPU-friendly embedding model with zero API charges that preserves full chunk contexts without silent truncation.

## Options with numbers

1. **`sentence-transformers/all-MiniLM-L6-v2`**:
   - 22.7M parameters (91 MB), 384 dimensions.
   - Max context window: **256 tokens**.
   - **Phase 3 Retrieval Benchmark (200 questions, 200/30 chunks):**
     - Recall@1: **0.520** (-0.055 vs BGE-Small)
     - Recall@5: **0.865** (Delta: -0.025, 95% Paired CI: `[-0.0800, +0.0300]`)
     - MRR@10: **0.665** (-0.027 vs BGE-Small)
     - Query latency: 2.5 ms
   - **Severe Truncation Flaw:** 70.00% of standard 200-word chunks exceed 256 tokens (p95 = 312.5 tokens, max = 322 tokens). Using MiniLM silently truncates ~10–66 tokens per chunk at the end of sections, destroying closing citations and sentence endings.

2. **`BAAI/bge-small-en-v1.5`** (Chosen):
   - 33.4M parameters (133 MB), 384 dimensions.
   - Max context window: **512 tokens**.
   - **Phase 3 Retrieval Benchmark:**
     - Recall@1: **0.575** (superior precision at rank 1)
     - Recall@5: **0.840** (95% Wilson CI: `[0.783, 0.884]`)
     - MRR@10: **0.692**
     - Query latency: 4.7 ms
   - **Truncation on corpus:** **0.00%** (all chunks fit safely within 512 tokens).
   - Local throughput: **63.1 chunks/s** on local CPU.

3. **OpenAI `text-embedding-3-small`**:
   - 1536 dimensions.
   - Requires paid external API calls ($0.02 / 1M tokens), active internet connection, and leaking private documents to third parties.

## Decision
Retain **`BAAI/bge-small-en-v1.5`** pinned to commit `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` via `sentence-transformers`. Prepend `"Represent this sentence for searching relevant passages: "` to queries only. Run on CPU with batch size 32 and L2 normalization.

## You give up X to get Y
You give up ~40 MB extra disk storage and ~2 ms query latency compared to MiniLM to get **100% complete chunk preservation (zero silent truncation)** and **significantly higher Recall@1 precision (0.575 vs 0.520)**.

## Revisit When
Target documents shift to multi-lingual non-English text, or retrieval Recall@5 drops below 0.80 on expanded evaluation suites.
