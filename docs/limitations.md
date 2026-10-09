# DocuMind Known Limitations & Failure Modes

This document records the top known failure modes identified during Phase 3 systematic error analysis (`docs/ERROR_ANALYSIS.md`).

---

## 1. Adversarial Lexical Overlap & Hard Negatives (Under-Abstention)
- **Description:** Bi-encoder embedding models (such as `bge-small-en-v1.5`) map queries to dense vectors via average pooling over token representations. When an adversarial or unanswerable query (e.g., SQuAD 2.0 impossible questions) shares heavy lexical and topical overlap with an indexed document (e.g. *"What did the UK ban on Sundays due to the embargo?"* matched against an oil crisis article discussing UK embargo measures), the similarity score exceeds the abstention threshold ($\tau = 0.35$, scoring $0.65 - 0.70$).
- **Impact:** Stage 2 retrieval thresholding does not filter these adversarial hard negatives. Filtering depends entirely on the downstream LLM adhering to Stage 5 (`DECLINE_SENTINEL`). Weak or eager generator models may hallucinate an answer.
- **Future Mitigation (Phase 4/5):** Incorporate a cross-encoder reranker trained on hard negatives or an explicit entailment classifier before response generation.

---

## 2. Artificial Boundary Cuts under Low Overlap
- **Description:** Fixed-window chunking cut strictly by word counts can split an atomic factual proposition across two separate chunks when overlap is zero or inadequate.
- **Impact:** An 8-word continuous answer snippet straddles a chunk boundary ($(\text{window}-1)/\text{step} \approx 3.5\%$ in 200-word chunks), rendering neither chunk a complete match for the gold snippet (`no_gold` failure).
- **Current Mitigation:** Locked default configuration of `chunk_size = 200` with `overlap = 30` words guarantees that no 8-word window is lost at boundaries (`no_gold = 0`).

---

## 3. Intra-Document Semantic Competition
- **Description:** For lengthy, cohesive technical documents (e.g., complex legal treaties or operating system architecture manuals), multiple paragraphs discuss identical terminology with subtle semantic differences.
- **Impact:** Broad user questions frequently retrieve general introductory or summary sections at Rank 1, pushing the exact definition or quantitative answer into Ranks 2–4. This creates a gap between Recall@1 (~0.57) and Recall@5 (~0.84).
- **Current Mitigation:** Retrieval top-k parameter defaults to `top_k = 5` and prompt context includes all top-k retrieved chunks, allowing the generation model to synthesize evidence across complementary passages.
