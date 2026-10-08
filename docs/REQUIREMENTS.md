# DocuMind — Requirements & Scope Specification

## 1. Functional Requirements (FR)

| ID | Requirement | Verification Test / Gate |
|---|---|---|
| **FR1** | Index `.pdf`, `.txt`, and `.md` files up to 50 MB and 500 pages. | `tests/test_loader.py`, `tests/test_ingest.py` |
| **FR2** | Re-indexing the same file is idempotent with zero duplicates and clean stale-chunk removal on edits. | `tests/test_ingest.py` (`test_index_idempotent_skip`, `test_index_file_shrunk_no_stale_chunks`) |
| **FR3** | Nearest-neighbor vector queries return ranked `RetrievedChunk` items with cosine scores. | `tests/test_store_contract.py` |
| **FR4** | Chunker validates parameters strictly (`chunk_size > 0`, `0 <= overlap < chunk_size`). | `tests/test_chunker.py` |
| **FR5** | VectorStore supports atomic listing, querying, counting, and removing document sources. | `tests/test_store_contract.py` |
| **FR6** | Query semantic retrieval grounds technical questions into top-1 relevant chunk. | `tests/test_phase1_acceptance.py` |
| **FR7** | Chunking preserves every word across boundaries without data loss. | `tests/test_chunker.py` (`test_no_word_is_ever_dropped`) |
| **FR8** | Core engine has zero dependencies on interfaces (CLI, REST, MCP). | `tests/test_architecture.py` |
| **FR9** | All pipeline configuration loaded via `.env` or system environment variables without hardcoded singletons. | `tests/test_types_and_config.py` |

## 2. Non-Functional Requirements (NFR)

| ID | Requirement | Target | Phase 1 Measured |
|---|---|---|---|
| **NFR1** | Query cold-start latency | ≤ 20 s | 3.23 s |
| **NFR2** | Embedding throughput on local CPU | ≥ 20 chunks/s | 63.1 chunks/s |
| **NFR3** | Resident Memory at startup | ≤ 2.5 GB | 732 MB |
| **NFR4** | Zero chunk truncation | 100% chunks ≤ 512 tokens | 0.00% truncated (max 322 tokens) |
| **NFR5** | Dev cost | ₹0 / $0 | ₹0 (free local open-source models) |

## 3. Constraints

- Python 3.12 (≥ 3.10 supported).
- Local CPU inference only during Phase 1.
- No network access during retrieval queries after initial model cache.
