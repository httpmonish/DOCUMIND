# LLM-as-a-Judge Calibration Report

## 1. Overview and Objective
Before deploying an automated LLM judge (`JUDGE_VERSION = "j1"`) to score faithfulness and correctness across the evaluation benchmark, the judge's scoring criteria must be calibrated against human ground truth.

- **Question Set:** 20 questions drawn from hand-written test sets on public documents (`pep_0020.md` and `pep_0008.md`).
- **Human Gold Annotations:** Blind human evaluation stored in `evals/judge_gold.jsonl` grading claim-level support (`true/false`), 3-class answer correctness (`correct`, `partial`, `incorrect`), and query relevance (`true/false`).
- **Target Gate:** Observed agreement $\ge 0.85$ for both 3-class correctness and binary full faithfulness (all claims supported).

## 2. Calibration Results

| Metric | Sample Size ($n$) | Observed Agreement | Cohen's Kappa ($\kappa$) | Target Gate | Status |
|---|---|---|---|---|---|
| **3-Class Correctness** | 20 | 1.0000 | 1.0000 | $\ge 0.85$ | **PASS** |
| **Fully Faithful** | 20 | 1.0000 | 1.0000 | $\ge 0.85$ | **PASS** |

## 3. Analysis & Prompt Safeguards
1. **Prompt Version:** `j1` defined in `documind/core/eval_judge.py`.
2. **Data-Tag Isolation:** All retrieved evidence, user question, candidate answer, and reference answer are strictly wrapped in XML-style tags (`<evidence>`, `<question>`, `<answer>`, `<reference>`) with XML escaping (`html.escape(quote=False)`).
3. **Structured Schema:** The judge produces JSON exclusively:
   ```json
   {
     "claims": [{"text": "...", "supported": true}],
     "correctness": "correct|partial|incorrect",
     "relevant": true
   }
   ```
4. **Conclusion:** The judge prompt `j1` meets all inter-rater agreement gates ($\ge 0.85$) and is validated for evaluation scoring across dev and test splits.
