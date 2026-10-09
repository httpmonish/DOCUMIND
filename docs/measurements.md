# DocuMind Phase 1 Measurements

Hardware: Apple Silicon M-series (macOS arm64), 16 GB Unified Memory.
Date: 2026-10-08
Model: `BAAI/bge-small-en-v1.5` (revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`)

---

## 1. Embedding Benchmark (`scripts/bench_embed.py --n 200`)

| Metric | Measured Value |
|---|---|
| Synthetic Chunks (200 words each) | 200 |
| Model Load Time | 3.11 s |
| Encoding Time (batch_size=32) | 3.17 s |
| Throughput | **63.1 chunks/s** |
| Peak RSS Memory | **732.0 MB** |
| Output Dimensions | `(200, 384)` |

---

## 2. Token Length Distribution (`scripts/token_stats.py tests/fixtures`)

Evaluated on `tests/fixtures/os_notes.md` (1,494 words) and `tests/fixtures/hello.pdf` with standard 200/30 windowing:

| Metric | Measured Value |
|---|---|
| Total Chunks | 10 |
| p50 Tokens | 266.0 |
| p95 Tokens | 312.5 |
| p99 Tokens | 320.1 |
| Max Tokens | 322 |
| **Percentage > 256 Tokens** | **70.00%** |
| **Percentage > 512 Tokens** | **0.00%** |

### Critical Retrieval Insight
70.00% of standard 200-word chunks exceed 256 tokens. Had `all-MiniLM-L6-v2` been used, the final ~10–66 tokens of 7 out of 10 chunks would have been silently truncated, destroying end-of-chunk sentences and citations. `BAAI/bge-small-en-v1.5` provides a 512-token context window where 0.00% of chunks suffer truncation.

---

## 3. Storage & Search Performance

| Metric | Measured Value |
|---|---|
| Chroma Disk Usage (`du -sh ~/.documind/chroma`) | **644 KB** |
| `phase1_search.py` Cold Start Time | **3.23 s** |
| Top-1 Retrieval Cosine Score ("what is a semaphore") | **0.783** |
| Top-1 Chunk Retrieved | `os_notes.md#3` (correct semaphore passage) |

---

## 4. Phase 2 Score Calibration (`scripts/phase2_calibrate.py`)

Calibration performed against `tests/fixtures/os_notes.md` using `BAAI/bge-small-en-v1.5` embeddings on 15 on-topic questions vs. 15 off-topic questions:

| Question Group | Sample Count (n) | Min Score | Median Score | Max Score |
|---|---|---|---|---|
| **On-Topic** | 15 | 0.7246 | 0.7602 | 0.8349 |
| **Off-Topic** | 15 | 0.3234 | 0.4251 | 0.5425 |

### Threshold Selection
- Clean separation gap between max off-topic (`0.5425`) and min on-topic (`0.7246`).
- Phase 3 performed automated sweeps and Paired Bootstrap calibration across 200 SQuAD benchmark queries.

---

## 5. Phase 3 Calibration & Updated Evaluation Gates (§7 Corrections)

### Abstention Threshold Decision (ADR 0008)
- Calibration across 200 answerable SQuAD queries and unanswerable queries confirmed `DOCUMIND_MIN_SCORE = 0.35`.
- At $\tau = 0.35$, the false-abstention rate on answerable queries is **0.000 (0%)**, ensuring zero legitimate user questions are prematurely rejected by retrieval.

### B4.3 Evaluation Gates (Corrected per §7 Item 1)
The original Phase 2 gate of "unanswerable abstained $\ge 0.80$" was split into distinct operational criteria:
1. **False-Abstain Rate (Answerable queries):** Target $\le 0.10$.
   - *Measured Test Split:* **0.000** (95% Wilson CI: `[0.000, 0.149]`) — **PASS**
2. **Off-Topic Abstain Rate (Queries outside domain):** Target $\ge 0.90$.
   - *Measured Test Split:* **1.000** (95% Wilson CI: `[0.566, 1.000]`) — **PASS**
3. **SQuAD Impossible Abstain Rate (Adversarial hard negatives):** Target $\ge 0.60$.
   - *Measured Test Split:* **0.000** (95% Wilson CI: `[0.000, 0.390]`) — **FAIL**
   - High lexical overlap with indexed passages bypasses bi-encoder cosine filtering without a cross-attention reranker (documented in `docs/limitations.md`).


