# 0001. Embedding Model Selection

## Context
DocuMind converts raw text chunks from technical documents into dense semantic vector representations for similarity search. We require a fast, local, CPU-friendly embedding model with zero API charges that preserves full chunk contexts without silent truncation.

## Options with numbers
1. **`sentence-transformers/all-MiniLM-L6-v2`**:
   - 22.7M parameters (91 MB).
   - Max context window: **256 tokens**.
   - MTEB retrieval average: ~42.0.
   - **Defect:** On our benchmarked corpus, 70.00% of standard 200-word chunks exceed 256 tokens (p95 = 312.5 tokens, max = 322 tokens). Using MiniLM silently drops ~10–66 tokens per chunk at the end of sections.
2. **`BAAI/bge-small-en-v1.5`** (Chosen):
   - 33.4M parameters (133 MB).
   - Max context window: **512 tokens**.
   - MTEB retrieval average: ~51.7 (+9.7 points over MiniLM).
   - Local throughput: **63.1 chunks/s** on local CPU.
   - Truncation on corpus: **0.00%** (all chunks within 512 tokens).
3. **OpenAI `text-embedding-3-small`**:
   - 1536 dimensions.
   - Requires paid external API calls ($0.02 / 1M tokens), active internet connection, and leaking private documents to third parties.

## Decision
Adopt `BAAI/bge-small-en-v1.5` pinned to commit `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` via `sentence-transformers`. Prepend `"Represent this sentence for searching relevant passages: "` to queries only. Run on CPU with batch size 32 and L2 normalization.

## You give up X to get Y
You give up ~40 MB extra disk storage and slightly higher compute requirements compared to MiniLM to get **100% complete chunk preservation (zero truncation)** and **+9.7 points higher retrieval precision**.

## Revisit when
Target documents shift to multi-lingual non-English text, or retrieval Recall@5 drops below 0.85 on expanded evaluation suites.
