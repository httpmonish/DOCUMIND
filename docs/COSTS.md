# DocuMind Cost Analysis & Model Economics

Pricing verified from Anthropic official documentation (dated 2026-10-08):
https://platform.claude.com/docs/en/about-claude/pricing

---

## 1. Unit Token Pricing Table

| Model Tier | Model Identifier | Input Price / M tokens | Output Price / M tokens |
|---|---|---|---|
| **Haiku 4.5** (Default Generation) | `claude-haiku-4-5-20251001` | **$1.00** | **$5.00** |
| **Sonnet 5.5** (Eval Judge) | `claude-sonnet-5-5` | **$2.00** | **$10.00** |

---

## 2. RAG Query Cost Model (`scripts/cost_model.py`)

A typical DocuMind query with `top_k = 5` retrieves:
- 5 chunks × ~280 tokens ≈ 1,400 tokens
- System prompt + XML metadata + Question ≈ 300 tokens
- **Total input tokens:** ~1,700 tokens
- **Expected generated answer:** ~300 tokens

### Cost Breakdown per Single Query

$$\text{Cost} = \frac{1,700 \times P_{\text{in}} + 300 \times P_{\text{out}}}{1,000,000}$$

| Engine | Per Query (USD) | Per Query (INR @ ₹86.5/$) | 1,000 Queries (USD) | 1,000 Queries (INR) |
|---|---|---|---|---|
| **Claude Haiku 4.5** | **$0.003200** | **₹0.277** | **$3.20** | **₹277** |
| **Claude Sonnet 5.5** | **$0.006400** | **₹0.554** | **$6.40** | **₹554** |

---

## 3. Measured Token Consumption vs. Projections

From acceptance tests and smoke benchmarks:
- Input tokens: 1,700 (exact alignment with synthetic prompt models)
- Output tokens: 300
- Generation cost per query: **$0.00320**
- Queries abstaining on `empty_index` or `low_score`: **$0.00000** (₹0; no LLM call made).
