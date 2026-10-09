# DocuMind Evaluation & Benchmark Report

## 1. Retrieval Baseline: Predictions vs. Measured Numbers

Evaluation performed over `evals/retrieval_set.jsonl` (n = 200 answerable questions from SQuAD 2.0 dev across 10 articles) using `BAAI/bge-small-en-v1.5` embeddings and exact `NumpyStore` search.

| Metric | Predicted (`PREDICTIONS.md`) | Measured Baseline | Delta | 95% Wilson CI |
|---|---|---|---|---|
| **Recall@1** | 0.620 | **0.575** | -0.045 | [0.506, 0.641] |
| **Recall@3** | — | **0.795** | — | [0.734, 0.845] |
| **Recall@5** | 0.860 | **0.840** | -0.020 | **[0.783, 0.884]** |
| **Recall@10** | — | **0.930** | — | [0.886, 0.958] |
| **MRR@10** | 0.720 | **0.692** | -0.028 | — |
| **no_gold** | 0 | **0** | 0 | — |
| **Latency (p50/p95)** | — | **4.8 ms / 5.9 ms** | — | — |

### Analysis of the Gap
The measured Recall@5 of 0.840 sits squarely within the predicted hypothesis and well inside the 95% Wilson confidence interval `[0.783, 0.884]`. The slight downward gap between predicted Recall@1 (0.620) and measured (0.575) highlights two distinct retrieval phenomena:
1. **Intra-article competition:** For multi-paragraph articles (e.g., `economic_inequality.md` or `force.md`), semantically adjacent paragraphs discussing the same conceptual topic frequently achieve marginally higher dot-product similarity than the specific paragraph containing the exact gold snippet, pushing the gold passage into ranks 2–4 (evident in the jump to Recall@3 = 0.795).
2. **Short/Broad queries:** A subset of SQuAD questions rely on broad topical phrasing that favors summary chunks rather than specific technical definitions. Crucially, `no_gold = 0` demonstrates that the 200-word window with 30-word overlap cleanly avoids snippet straddling, ensuring 100% of answerable questions possess at least one reachable gold chunk in the index.
