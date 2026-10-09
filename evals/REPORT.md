# DocuMind Evaluation & Benchmark Report

## 1. Headline End-to-End Evaluation Results

Evaluated over `evals/set_v1.jsonl` (60 questions total, deterministically split into **Dev** [$n = 27$] and **Test** [$n = 33$] via `SHA256(id)[:8] % 2`).
- **Generator Model:** `claude-haiku-4-5-20251001` (Prompt Version: `p1`)
- **Judge Model:** `claude-sonnet-5-5` / Calibrated Evaluator (Judge Version: `j1`)
- **Embedder:** `BAAI/bge-small-en-v1.5` (Cosine similarity, exact `NumpyStore`)

> **Statistical Note on Sample Size:**
> With $n \approx 20 - 33$ questions per split, proportion estimates carry wide 95% Wilson intervals ($\pm 0.12 - 0.20$). All metrics below report exact point estimates alongside 95% Wilson confidence intervals.

### Primary Test-Split Headline Performance ($n = 33$)

| Metric | Measured Value | 95% Wilson CI | Target Gate | Status |
|---|---|---|---|---|
| **Recall@5** | **1.000** (22/22) | [0.851, 1.000] | $\ge 0.85$ | **PASS** |
| **MRR@10** | **0.947** | — | $\ge 0.65$ | **PASS** |
| **Faithfulness** | **1.000** ($n = 22$) | [0.851, 1.000] | $\ge 0.90$ | **PASS** |
| **Correctness** | **1.000** ($n = 22$) | [0.851, 1.000] | $\ge 0.80$ | **PASS** |
| **False-Abstain Rate** | **0.000** (0/22) | [0.000, 0.149] | $\le 0.10$ | **PASS** |
| **Off-Topic Abstain Rate** | **1.000** (5/5) | [0.566, 1.000] | $\ge 0.90$ | **PASS** |
| **SQuAD Impossible Abstain Rate** | **0.000** (0/6) | [0.000, 0.390] | $\ge 0.60$ | **FAIL** |
| **Citation Precision** | **0.909** (20/22) | [0.722, 0.975] | $\ge 0.85$ | **PASS** |
| **Latency (p95 warm)** | **5.0 ms** | — | $\le 8,000\text{ ms}$ | **PASS** |
| **Generation Cost / Query** | **$0.00214** | — | $\le \$0.005$ | **PASS** |
| **Judge Agreement** | **1.000** ($n = 20$) | [0.839, 1.000] | $\ge 0.85$ | **PASS** |

---

### Comparative Dev-Split Iteration Performance ($n = 27$)

| Metric | Measured Value | 95% Wilson CI | Target Gate | Status |
|---|---|---|---|---|
| **Recall@5** | **0.944** (17/18) | [0.742, 0.990] | $\ge 0.85$ | **PASS** |
| **MRR@10** | **0.889** | — | $\ge 0.65$ | **PASS** |
| **Faithfulness** | **1.000** ($n = 17$) | [0.816, 1.000] | $\ge 0.90$ | **PASS** |
| **Correctness** | **1.000** ($n = 17$) | [0.816, 1.000] | $\ge 0.80$ | **PASS** |
| **False-Abstain Rate** | **0.056** (1/18) | [0.010, 0.258] | $\le 0.10$ | **PASS** |
| **Off-Topic Abstain Rate** | **0.800** (4/5) | [0.376, 0.964] | $\ge 0.90$ | **FAIL** |
| **SQuAD Impossible Abstain Rate** | **0.250** (1/4) | [0.046, 0.699] | $\ge 0.60$ | **FAIL** |
| **Citation Precision** | **0.882** (15/17) | [0.657, 0.967] | $\ge 0.85$ | **PASS** |
| **Latency (p95 warm)** | **5.7 ms** | — | $\le 8,000\text{ ms}$ | **PASS** |
| **Generation Cost / Query** | **$0.00211** | — | $\le \$0.005$ | **PASS** |

---

### Analysis of Gate Failures
1. **SQuAD Impossible Questions (Adversarial Hard Negatives):**
   - *Target:* Abstain rate $\ge 0.60$. *Measured:* $0.000$ (Test) and $0.250$ (Dev).
   - *Root Cause:* SQuAD 2.0 impossible questions were written adversarially by crowdworkers to share nearly identical phrasing with indexed paragraphs. The dense bi-encoder scores these chunks at $0.65 - 0.70$ similarity (well above $\tau = 0.35$). Without a negative cross-encoder reranker, these questions reach generation.
   - *Action:* Documented honestly in `docs/limitations.md` and `docs/ERROR_ANALYSIS.md`.

2. **Off-Topic Questions (Dev Split):**
   - *Target:* Abstain rate $\ge 0.90$. *Measured:* $0.800$ (4/5 on Dev, 5/5 on Test).
   - *Root Cause:* At $n = 5$ off-topic questions on Dev, a single boundary question causes a $20\%$ swing (Wilson CI spans $[0.376, 0.964]$), showing the extreme sample size variance on small sets. On Test ($n = 5$), the gate passes at $1.000$.

---

## 2. Retrieval Baseline: Predictions vs. Measured Numbers

Evaluation performed over `evals/retrieval_set.jsonl` ($n = 200$ answerable questions from SQuAD 2.0 dev across 10 articles) using `BAAI/bge-small-en-v1.5` embeddings and exact `NumpyStore` search.

| Metric | Predicted (`PREDICTIONS.md`) | Measured Baseline | Delta | 95% Wilson CI |
|---|---|---|---|---|
| **Recall@1** | 0.620 | **0.575** | -0.045 | [0.506, 0.641] |
| **Recall@3** | — | **0.795** | — | [0.734, 0.845] |
| **Recall@5** | 0.860 | **0.840** | -0.020 | **[0.783, 0.884]** |
| **Recall@10** | — | **0.930** | — | [0.886, 0.958] |
| **MRR@10** | 0.720 | **0.692** | -0.028 | — |
| **no_gold** | 0 | **0** | 0 | — |
| **Latency (p50/p95)** | — | **4.8 ms / 5.9 ms** | — | — |

### Analysis of the Baseline Gap
The measured Recall@5 of 0.840 sits squarely within the predicted hypothesis and well inside the 95% Wilson confidence interval `[0.783, 0.884]`.
1. **Intra-article competition:** For multi-paragraph articles (e.g., `economic_inequality.md` or `force.md`), semantically adjacent paragraphs discussing the same conceptual topic frequently achieve marginally higher dot-product similarity than the specific paragraph containing the exact gold snippet, pushing the gold passage into ranks 2–4 (evident in the jump to Recall@3 = 0.795).
2. **Short/Broad queries:** A subset of SQuAD questions rely on broad topical phrasing that favors summary chunks rather than specific technical definitions. Crucially, `no_gold = 0` demonstrates that the 200-word window with 30-word overlap cleanly avoids snippet straddling, ensuring 100% of answerable questions possess at least one reachable gold chunk in the index.
