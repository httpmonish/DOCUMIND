# DocuMind Evaluation Suite & Retrieval Benchmark

## 1. Retrieval Benchmark Overview

The retrieval benchmark dataset (`evals/retrieval_set.jsonl`) contains **200 answerable questions** auto-labelled from the public SQuAD 2.0 development set across 10 distinct topical articles:
- `1973_oil_crisis`
- `amazon_rainforest`
- `black_death`
- `civil_disobedience`
- `computational_complexity_theory`
- `construction`
- `ctenophora`
- `economic_inequality`
- `european_union_law`
- `force`

Additionally, `evals/squad_impossible.jsonl` contains **10 adversarial unanswerable questions** (`is_impossible: true`) from the same indexed articles.

---

## 2. Quality Audit (30-Question Sample)

A manual audit of 30 randomly sampled questions from `retrieval_set.jsonl` was conducted:
- **Clear & Domain-Specific (27/30, 90.0%):** Questions contain specific entities, proper nouns, or unambiguous technical terminology (e.g., *"How quickly can an algorithm solve an NP-complete knapsack problem?"*, *"In which case were French vigilantes sabotaging shipments of Spanish Strawberries?"*).
- **Ambiguous Without Passage (3/30, 10.0%):**
  - *"What do those in the field do to ensure a positive outcome?"* (`construction.md`) — generic pronoun reference.
  - *"What would be lower if there were fewer people?"* (`economic_inequality.md`) — broad scope without article context.
  - *"The owner typically awards a contract to who?"* (`construction.md`) — assumes project management contract context.

---

## 3. Known Label Bias & Boundary Cuts

Labels are defined as normalized 8-word text windows (`gold_snippets = [gold_window(context, answer_start, 8)]`), rather than static chunk IDs, ensuring evaluation validity across varying chunk sizes and overlaps.

**Boundary Cut Bias (Locked Decision §6):**
With `overlap = 0`, an 8-word window can straddle an arbitrary chunk boundary. When this happens, neither chunk contains the full 8-word sequence, resulting in `is_gold == False` for all retrieved chunks even if the surrounding sentences were retrieved. This affects approximately:
$$\frac{\text{window} - 1}{\text{step}} \approx \frac{7}{200} = 3.5\% \text{ of questions}$$
counted as misses (`no_gold`). With `overlap >= 30`, this straddling cannot happen because the overlap window exceeds the 8-word snippet length. This represents a real physical effect of boundary cutting in production RAG systems, but also a known bias of the substring label evaluation method.
