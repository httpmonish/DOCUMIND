# DocuMind Failure & Error Analysis

A systematic classification of 16 observed evaluation failures across retrieval benchmarks, sweep configurations, and end-to-end evaluation runs.

---

## 1. Failure Taxonomy & Distribution

| Failure Class | Count | Root Cause Category | Primary Mitigation |
|---|---|---|---|
| **Retrieval Miss** | 3 | Dense semantic mismatch | Query expansion or hybrid BM25 + dense retrieval |
| **Boundary Cut** | 2 | Chunk boundary straddles gold context | Overlap $\ge 30$ words (fixed in default settings) |
| **Ambiguous / Mislabelled Question** | 3 | SQuAD dataset context dependency | Question filtering heuristics during benchmark construction |
| **Judge Error** | 2 | LLM judge parsing / strictness discrepancy | Calibrated prompt guidelines & few-shot schema enforcement |
| **Model Hallucination** | 2 | Extrapolation beyond retrieved evidence | Strict negative prompting and decline sentinel policy |
| **Over-Abstention** | 1 | Marginal cosine similarity below threshold | Calibrated score threshold $\tau = 0.35$ |
| **Under-Abstention** | 3 | Adversarial hard negatives with high lexical overlap | Cross-encoder reranker or negative intent classifier |
| **Total Failures Analyzed** | **16** | — | — |

---

## 2. Detailed Classification & Examples

### Class 1: Retrieval Miss (Count: 3)
- **Failure 1.1:** Question ID `572620ad271a42140099d45e`
  - *Quote:* *"What biological feature do ctenophores use for locomotion in water?"*
  - *Observed behavior:* The dense embedder retrieved generic introductory morphology chunks over the specific locomotion passage; gold chunk ranked at rank 8 (miss for Recall@5).
  - *Proposed fix:* Hybrid sparse-dense retrieval (BM25 + BGE) to capture domain-specific lexical terms like "cilia" and "comb rows".
- **Failure 1.2:** Question ID `57266a2b5951b619008f731a`
  - *Quote:* *"What was the primary economic consequence of the oil embargo on Western shipping?"*
  - *Observed behavior:* Gold chunk ranked at rank 7 due to dense competition with macro-economic policy chunks.
  - *Proposed fix:* Contextual document header prepend to inject article-level topic anchoring into every chunk.
- **Failure 1.3:** Question ID `572798e4ff5b5019007d9f78`
  - *Quote:* *"Which legal institution resolves jurisdictional disputes within the European Community?"*
  - *Observed behavior:* Broad conceptual embedding placed the ECJ dispute chunk outside the top-5 window.
  - *Proposed fix:* Increase `top_k` from 5 to 7 or introduce reciprocal rank fusion (RRF).

### Class 2: Boundary Cut (Count: 2)
- **Failure 2.1:** Question ID `5727c9c0ff5b5019007da1b2` (under sweep configuration `chunk_size=120, overlap=0`)
  - *Quote:* *"The 8-word gold snippet was bisected across chunk 0012 and chunk 0013."*
  - *Observed behavior:* `no_gold` flag triggered; neither chunk contained the complete 8-word continuous snippet.
  - *Proposed fix:* Enforce minimum overlap $\ge 30$ words (validated: `no_gold = 0` at overlap $\ge 30$).
- **Failure 2.2:** Question ID `57281f62ff5b5019007da45a` (under configuration `chunk_size=200, overlap=0`)
  - *Quote:* *"Key numerical fact and qualifying condition separated at sentence boundary."*
  - *Observed behavior:* Gold snippet split across boundary cut; retrieval failed to match complete ground truth.
  - *Proposed fix:* Sentence-aware chunk boundary splitting instead of fixed-word chunking.

### Class 3: Ambiguous or Mislabelled Question (Count: 3)
- **Failure 3.1:** Question ID `57285268ff5b5019007da72b`
  - *Quote:* *"Who was he referring to in the second paragraph of the text?"*
  - *Observed behavior:* Query lacks explicit referent without seeing the paragraph text; retrieval retrieved wrong entity.
  - *Proposed fix:* Filter standalone queries lacking concrete named entities or containing dangling pronouns.
- **Failure 3.2:** Question ID `572886ecff5b5019007da99c`
  - *Quote:* *"How much did it increase over that period of time?"*
  - *Observed behavior:* Query is unanswerable without preceding conversational context or date specifications.
  - *Proposed fix:* Automated interrogative quality filter rejecting queries without temporal or nominal anchors.
- **Failure 3.3:** Question ID `5728b9d5ff5b5019007dac0e`
  - *Quote:* *"What happened next according to the third recorded account?"*
  - *Observed behavior:* Structural index references ("the third account") do not persist across isolated document chunks.
  - *Proposed fix:* Exclude document-relative ordinal queries during eval benchmark construction.

### Class 4: Judge Error (Count: 2)
- **Failure 4.1:** Question ID `eval_judge_synonym_01`
  - *Quote:* *"Candidate answer used 'four spaces' while reference specified '4 spaces'."*
  - *Observed behavior:* Judge initially flagged claim as partial due to literal string matching bias before normalization.
  - *Proposed fix:* Explicitly instruct the judge prompt that linguistic paraphrases and equivalent numeric notations are fully supported.
- **Failure 4.2:** Question ID `eval_judge_schema_02`
  - *Quote:* *"Model output included conversational preamble before emitting JSON block."*
  - *Observed behavior:* Triggered regex fallback parser; potential `JudgeParseError` risk on weak models.
  - *Proposed fix:* Enforce system prompt demanding strict JSON only and strip markdown fences in `parse_judge_output`.

### Class 5: Model Hallucination (Count: 2)
- **Failure 5.1:** Question ID `own_halluc_01`
  - *Quote:* *"The GIL was created by Guido in 1991 to prevent race conditions."*
  - *Observed behavior:* Generator answered with correct real-world history not stated anywhere in `python_gil.md`.
  - *Proposed fix:* Strengthen System Policy #1: *"Use only information found in the sources. Do not extrapolate."*
- **Failure 5.2:** Question ID `own_halluc_02`
  - *Quote:* *"SQLite uses a B*Tree with 512-byte headers on page one."*
  - *Observed behavior:* Model introduced specific external SQLite internals absent from `sqlite_basics.md`.
  - *Proposed fix:* Strict citation alignment check stripping claims unsupported by cited chunks.

### Class 6: Over-Abstention (Count: 1)
- **Failure 6.1:** Question ID `own_08`
  - *Quote:* *"What should you refuse in the face of ambiguity?"*
  - *Observed behavior:* Top retrieved chunk scored 0.630, but generator emitted generic decline because chunk 13 of `civil_disobedience.md` was retrieved rather than `pep_0020.md`.
  - *Proposed fix:* Re-indexing with metadata source filtering to restrict retrieval scope when collection is known.

### Class 7: Under-Abstention (Count: 3)
- **Failure 7.1:** Question ID `5a38baa2a4b263001a8c18d9` (SQuAD Impossible)
  - *Quote:* *"What did the UK ban on Sundays due to the embargo?"*
  - *Observed behavior:* Retrieved chunks from `1973_oil_crisis.md` scored 0.682 due to high lexical overlap with "UK", "Sundays", "embargo". Generator attempted to construct an answer.
  - *Proposed fix:* Deploy negative intent classification or cross-attention reranker (Phase 4).
- **Failure 7.2:** Question ID `5a0c7edcf5590b0018dab43c` (SQuAD Impossible)
  - *Quote:* *"A 1999 study found that 100 km² contain how many plants?"*
  - *Observed behavior:* Retrieved chunk scored 0.668 from `amazon_rainforest.md` (which mentions a 2001 study with different numbers); model answered with the 2001 study numbers.
  - *Proposed fix:* Add strict temporal and entity discrepancy checks before synthesis.
- **Failure 7.3:** Question ID `5ad261cfd7d075001a429066` (SQuAD Impossible)
  - *Quote:* *"What hasn't given the American economy a tendency to go bubble to bubble?"*
  - *Observed behavior:* Negative syntactic inversion ("hasn't given") scored 0.705 against economic inequality text discussing bubble tendencies.
  - *Proposed fix:* Calibrate negative interrogative detection.

---

## 3. Top 3 Known Failure Cases (Transferred to `docs/limitations.md`)
1. **Adversarial Lexical Overlap (Under-Abstention on SQuAD Impossible):** Bi-encoder embeddings match queries sharing high lexical overlap with indexed context, even when the specific question is unanswerable.
2. **Snippet Bisecting on Zero Overlap:** Chunks with zero overlap can divide ground-truth definitions across artificial window boundaries.
3. **Intra-Document Conceptual Competition:** In dense technical documents, broad queries retrieve neighboring conceptual sections rather than exact target passages.
