# 0003. Text Chunking Strategy

## Context
Raw documents range from short summaries to 500-page textbooks. Document text must be segmented into coherent, overlapping chunks suitable for dense vector embedding and LLM prompt context injection.

## Options with numbers
1. **Sentence-level chunking (e.g. NLTK/spaCy)**:
   - High dependency overhead (~100 MB model/tokenizer dependencies).
   - High variance in chunk token lengths; single sentences lack broader context.
2. **Fixed character sliding windows**:
   - Simple, but frequently splits words and technical code identifiers mid-token.
3. **Word window (3x3 parameter grid measured in Phase 3)**:
   Evaluated across 200 answerable SQuAD benchmark questions (paired bootstrap with 2,000 resamples):

| Config (Size/Overlap) | Total Chunks | Recall@1 | Recall@5 | MRR@10 | Delta vs Baseline (95% Paired CI) | Label Straddles (`no_gold`) |
|---|---|---|---|---|---|---|
| `120 / 0` | 385 | 0.595 | 0.830 | 0.690 | -0.0100 ([-0.0700, +0.0500]) | 10 (3.5% bias) |
| `120 / 30` | 510 | 0.630 | 0.870 | 0.729 | +0.0300 ([-0.0150, +0.0800]) | 0 |
| `120 / 60` | 755 | 0.660 | 0.860 | 0.756 | +0.0200 ([-0.0200, +0.0650]) | 0 |
| `200 / 0` | 233 | 0.535 | 0.835 | 0.666 | -0.0050 ([-0.0550, +0.0450]) | 7 (2.6% bias) |
| **`200 / 30` (Baseline)** | **272** | **0.575** | **0.840** | **0.692** | **+0.0000 ([0.0000, 0.0000])** | **0** |
| `200 / 60` | 327 | 0.560 | 0.860 | 0.696 | +0.0200 ([-0.0200, +0.0601]) | 0 |
| `300 / 0` | 157 | 0.550 | 0.855 | 0.675 | +0.0150 ([-0.0350, +0.0650]) | 4 (1.5% bias) |
| `300 / 30` | 173 | 0.520 | 0.875 | 0.663 | +0.0350 ([-0.0150, +0.0850]) | 0 |
| `300 / 60` | 193 | 0.565 | 0.860 | 0.694 | +0.0200 ([-0.0300, +0.0700]) | 0 |

## Decision
Retain default **`chunk_size = 200` words and `overlap = 30` words**.
Per the Locked Decision §6 rule, a change is adopted only if the paired bootstrap 95% lower bound is > 0 and the mean improvement is >= +0.05. None of the candidate configurations satisfy this requirement (all 95% intervals span zero). Furthermore, 200/30 offers optimal balance between chunk granularity (272 chunks), zero label straddling (`no_gold = 0`), and low index memory footprint.

## You give up X to get Y
You give up minor potential Recall@5 gains (+0.035 at 300/30) to get **lower prompt context overhead, faster top-k retrieval, and statistically robust performance without parameter churn**.

## Revisit When
Adding semantic rerankers or parent-document retrieval in future architectural revisions.
