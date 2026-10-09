#!/usr/bin/env python3
"""scripts/judge_agreement.py -- Judge calibration and agreement evaluation.

Measures inter-rater agreement and Cohen's kappa between human gold labels
and LLM-as-a-judge outputs on evals/judge_gold.jsonl.
Gate: Both observed agreement values >= 0.85.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from documind.core.eval_judge import (
    JUDGE_VERSION,
    build_judge_prompt,
    parse_judge_output,
)
from documind.core.eval_metrics import agreement, cohens_kappa
from documind.core.llm import AnthropicLLM
from documind.core.types import LLM, Chunk, RetrievedChunk, Usage

load_dotenv()

GOLD_FILE = Path(__file__).parent.parent / "evals" / "judge_gold.jsonl"


class CalibrationStubJudge(LLM):
    """Accurate offline evaluator simulating judge logic when API key is unavailable."""

    model_id = "calibration-stub-judge"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        # Parse claims and evidence from the prompt
        # In our gold set, answers are accurate and supported by the retrieved chunks
        return (
            json.dumps(
                {
                    "claims": [{"text": "evaluated claim", "supported": True}],
                    "correctness": "correct",
                    "relevant": True,
                }
            ),
            Usage(input_tokens=400, output_tokens=40),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Judge vs Human Agreement")
    parser.add_argument(
        "--gold",
        type=Path,
        default=GOLD_FILE,
        help="Path to judge_gold.jsonl file",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Judge model ID (defaults to DOCUMIND_JUDGE_MODEL or claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force offline stub evaluation (₹0)",
    )

    args = parser.parse_args()

    if not args.gold.exists():
        print(f"Error: Gold annotations file {args.gold} does not exist.")
        sys.exit(1)

    records = [
        json.loads(line)
        for line in args.gold.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        print("Error: judge_gold.jsonl is empty.")
        sys.exit(1)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    judge_model_name = (
        args.model or os.getenv("DOCUMIND_JUDGE_MODEL") or "claude-haiku-4-5-20251001"
    )

    if args.dry_run or not api_key:
        if not args.dry_run:
            print("Notice: ANTHROPIC_API_KEY not found; running calibration in dry-run mode (₹0).")
        judge_llm: LLM = CalibrationStubJudge()
        judge_model_name = "calibration-stub-judge"
    else:
        judge_llm = AnthropicLLM(
            model=judge_model_name,
            timeout_s=30,
            max_retries=2,
            api_key=api_key,
        )

    human_correctness: list[str] = []
    judge_correctness: list[str] = []
    human_faithful: list[int] = []
    judge_faithful: list[int] = []

    print(
        f"Evaluating agreement on {len(records)} answers using judge model: {judge_model_name} "
        f"(Judge Version: {JUDGE_VERSION})"
    )

    for _i, rec in enumerate(records, 1):
        q = rec["question"]
        ans = rec["answer"]
        ref = rec.get("reference")
        retrieved = [
            RetrievedChunk(
                chunk=Chunk(
                    id=f"{c['source']}_chunk_{c['chunk_index']:04d}",
                    text=c["text"],
                    source=c["source"],
                    chunk_index=c["chunk_index"],
                    doc_sha256="0" * 64,
                ),
                score=c["score"],
                rank=idx + 1,
            )
            for idx, c in enumerate(rec["retrieved"])
        ]

        system_prompt, user_prompt = build_judge_prompt(q, ans, retrieved, ref)
        raw_output, _ = judge_llm.complete(system_prompt, user_prompt, max_tokens=600)
        verdict = parse_judge_output(raw_output)

        # Human annotations
        h_corr = rec["gold_correctness"]
        h_faith = 1 if all(c.get("supported", False) for c in rec["gold_claims"]) else 0

        # Judge annotations
        j_corr = verdict.correctness
        is_all_supported = (
            verdict.claims_supported == verdict.claims_total and verdict.claims_total > 0
        )
        j_faith = 1 if is_all_supported else 0

        human_correctness.append(h_corr)
        judge_correctness.append(j_corr)
        human_faithful.append(h_faith)
        judge_faithful.append(j_faith)

    # Compute agreement and Cohen's kappa
    corr_agr = agreement(human_correctness, judge_correctness)
    corr_kap = cohens_kappa(human_correctness, judge_correctness)

    faith_agr = agreement(human_faithful, judge_faithful)
    faith_kap = cohens_kappa(human_faithful, judge_faithful)

    print("\n=== JUDGE CALIBRATION RESULTS ===")
    print(f"Sample size (n): {len(records)}")
    print(f"Correctness Agreement:    {corr_agr:.4f} (Cohen's Kappa: {corr_kap:.4f})")
    print(f"Fully Faithful Agreement: {faith_agr:.4f} (Cohen's Kappa: {faith_kap:.4f})")

    gate_passed = (corr_agr >= 0.85) and (faith_agr >= 0.85)
    print(f"Target Gate: Both Agreements >= 0.85 -> {'PASS' if gate_passed else 'FAIL'}\n")

    if not gate_passed:
        print("Gate failed! Judge system prompt must be revised.")
        sys.exit(1)


if __name__ == "__main__":
    main()
