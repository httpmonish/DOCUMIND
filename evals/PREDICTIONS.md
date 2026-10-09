# Retrieval Baseline Predictions (Pre-Measurement)

Written and committed prior to executing the baseline retrieval benchmark run.

## Target Predictions (Config: chunk_size=200, overlap=30, embed_model=BAAI/bge-small-en-v1.5)

| Metric | Predicted Value | Rationale |
|---|---|---|
| **Recall@1** | **0.62** | Top-1 retrieval will often hit the exact paragraph due to dense lexical/semantic overlap, but will occasionally favor adjacent chunks within the same article. |
| **Recall@5** | **0.86** | 5 chunks give ~1,000 words of window across a ~2,000-word article, capturing the gold snippet in the vast majority of direct factual questions. |
| **MRR@10** | **0.72** | With most correct chunks ranked 1st or 2nd (reciprocal ranks 1.0 or 0.5), the harmonic mean should hover around 0.70–0.75. |

### Prediction Hypothesis
The 200-word chunk size with 30-word overlap provides strong preservation of local paragraph context while ensuring that the 8-word answer snippets never straddle boundaries. Residual misses are expected primarily from short, ambiguous queries or vocabulary divergence where the query lacks specific named entities.
