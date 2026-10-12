# DocuMind Cost Analysis & Model Economics

Pricing verified from Anthropic official documentation (dated 2026-10-08):
https://platform.claude.com/docs/en/about-claude/pricing

---

## 1. Unit Token Pricing Table

| Model Tier | Model Identifier | Input Price / M tokens | Output Price / M tokens |
|---|---|---|---|
| **Haiku 4.5** (Default Generation) | `claude-haiku-4-5-20251001` | **$1.00** | **$5.00** |
| **Sonnet 5.5** (Eval Judge / Headline) | `claude-sonnet-5-5` | **$2.00** | **$10.00** |

---

## 2. RAG Query Cost Model (`scripts/cost_model.py`)

A typical DocuMind query with `top_k = 5` retrieves:
- 5 chunks × ~280 tokens ≈ 1,400 tokens
- System prompt + XML metadata + Question ≈ 300 tokens
- **Total input tokens:** ~1,700 tokens
- **Expected generated answer:** ~300 tokens

### Cost Breakdown per Single Query (Measured vs Estimated)

$$\text{Cost} = \frac{1,700 \times P_{\text{in}} + 300 \times P_{\text{out}}}{1,000,000}$$

| Engine | Per Query (USD) | Per Query (INR @ ₹86.5/$) | 1,000 Queries (USD) | 1,000 Queries (INR) |
|---|---|---|---|---|
| **Claude Haiku 4.5** | **$0.003200** | **₹0.277** | **$3.20** | **₹277** |
| **Claude Sonnet 5.5** (Standard) | **$0.006400** | **₹0.554** | **$6.40** | **₹554** |
| **Claude Sonnet 5.5** (1.3× Tokenizer Factor) | **$0.008320** | **₹0.720** | **$8.32** | **₹720** |

---

## 3. Measured Token Consumption from Phase 3 E2E Evaluation

From the Phase 3 benchmark runs (`scripts/run_eval.py` over 60 questions):
- **Average generation input tokens:** ~1,700 tokens
- **Average generation output tokens:** ~80–120 tokens (concise grounded responses)
- **Measured generation cost per query:** **$0.00214** (comfortably below the $\le \$0.005$ gate)
- **Queries abstaining on `empty_index` or `low_score`:** **$0.00000** (₹0; no LLM call invoked).
- **Judge evaluation cost per question (Haiku 4.5):** ~$0.00075 / call
- **Judge evaluation cost per question (Sonnet 5.5):** ~$0.00160 / call

---

## 4. Public Demo Spend Hardening & Daily Caps (Phase B)

To guarantee that the public demo never exceeds budget or incurs unexpected API bills:
- **Global Daily Cap:** **$2.00 / day** (`DOCUMIND_GLOBAL_DAILY_CAP_USD`).
- **Per-IP Daily Cap:** **$0.25 / day** (`DOCUMIND_IP_DAILY_CAP_USD`).
- **Two-Phase Commit Ledger (`SpendLedger`):**
  1. *Reserve*: Prior to invoking generative LLM inference, an estimated upper-bound cost (~2,000 input tokens + max tokens output = ~$0.005) is atomically reserved in SQLite.
  2. *Settle*: Upon successful completion, actual measured tokens (`ans.usage.input_tokens` and `ans.usage.output_tokens`) are settled and any reserved surplus is released.
  3. *Release*: If the client disconnects or an internal error occurs, the entire reservation is released immediately.
- **Fail-Closed Retrieval-Only Mode:**
  When either cap is breached, the API **never** crashes or returns an ugly HTTP 500. Instead, it responds with HTTP 200 in honest `outcome="retrieval_only"` mode, serving the vector store's retrieved passages and citations without generative synthesis.
