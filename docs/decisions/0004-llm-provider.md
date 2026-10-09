# ADR 0004: LLM Provider Selection

## Status
Accepted

## Date
2026-10-08

## Context
DocuMind requires an LLM for synthesizing answers strictly grounded in retrieved document chunks. The model must strictly follow complex system instructions (such as refusing to answer when ungrounded, citing specific source markers `[S1]`, and ignoring prompt injections inside untrusted document chunks). Key operational constraints include cost efficiency for student budgets, low inference latency, and high instruction adherence.

## Options Considered

1. **Anthropic Claude Haiku 4.5 (`claude-haiku-4-5-20251001`):**
   - Cost: $1.00 / million input tokens, $5.00 / million output tokens.
   - Cost per standard RAG query (~1,700 in, 300 out): **$0.0032 (≈ ₹0.28)**.
   - Latency: ~1.0–2.2 s warm.
   - High instruction adherence to XML tag escaping and refusal sentinels.

2. **Anthropic Claude Sonnet 5.5 (`claude-sonnet-5-5`):**
   - Cost: $2.00 / million input tokens, $10.00 / million output tokens.
   - Cost per query: **$0.0064–$0.0083 (≈ ₹0.55–₹0.72)** (2x–2.6x higher cost).
   - Latency: ~2.5–5.0 s.
   - Higher reasoning capability, ideal as an evaluation judge rather than primary generation engine.

3. **Local LLM via Ollama (e.g. Llama-3.2-3B / Phi-3-Mini):**
   - Cost: ₹0 API cost.
   - Latency: 40–75 s per query on 8 GB RAM laptop CPU without discrete GPU.
   - Prone to hallucinating citations or leaking canary prompts under adversarial context.

## Decision
Adopt **Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)** as the primary default generation model.

## Trade-offs
- **Gained:** Sub-2 second generation latency, reliable citation adherence, strong prompt injection resistance, and ultra-low cost ($0.0032/query).
- **Sacrificed:** Free offline generation (requires Anthropic API key and internet connectivity).

## Revisit When
- High-efficiency quantized models (e.g. 4-bit GGUF via llama.cpp) achieve sub-5s latency on commodity laptop CPUs with proven citation adherence.
