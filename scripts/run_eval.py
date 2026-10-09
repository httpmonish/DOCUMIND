#!/usr/bin/env python3
"""scripts/run_eval.py -- Evaluation runner with dev/test split, dry-run, and reporting."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from documind.core.config import Settings
from documind.core.embedder import SentenceTransformerEmbedder
from documind.core.eval_judge import JUDGE_VERSION
from documind.core.eval_runner import (
    BudgetExceeded,
    EvalQuestion,
    run_e2e,
    summarize,
)
from documind.core.ingest import index_path
from documind.core.llm import AnthropicLLM
from documind.core.pipeline import DocuMind
from documind.core.prompt import PROMPT_VERSION
from documind.core.types import LLM, Usage
from documind.core.vector_store import ChromaStore, NumpyStore

load_dotenv()

DEFAULT_SET = Path(__file__).parent.parent / "evals" / "set_v1.jsonl"
CORPUS_DIR = Path(__file__).parent.parent / "evals" / "corpus"
OWN_CORPUS_DIR = Path(__file__).parent.parent / "evals" / "corpus_own"
RUNS_DIR = Path(__file__).parent.parent / "evals" / "runs"


class StubGenerator(LLM):
    """₹0 offline stub generator for dry-run validation."""

    model_id = "stub-generator"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        from documind.core.prompt import DECLINE_SENTINEL

        q_match = re.search(r"<question>(.*?)</question>", user, re.DOTALL)
        q_text = q_match.group(1).lower() if q_match else ""
        sources_match = re.search(r"<sources>(.*?)</sources>", user, re.DOTALL)
        sources_text = sources_match.group(1).lower() if sources_match else ""

        stopwords = {
            "what",
            "who",
            "when",
            "where",
            "why",
            "how",
            "is",
            "are",
            "the",
            "a",
            "an",
            "in",
            "on",
            "of",
            "to",
            "for",
            "did",
            "does",
            "do",
            "by",
            "due",
            "that",
            "this",
            "from",
            "with",
            "about",
            "into",
            "their",
        }
        words = [w for w in re.findall(r"\w+", q_text) if w not in stopwords and len(w) > 2]

        # For off-topic / unanswerable queries where content words are missing from sources:
        matching = [w for w in words if w in sources_text]
        if words and (len(matching) / len(words) < 0.5):
            return DECLINE_SENTINEL, Usage(input_tokens=1700, output_tokens=15)

        return "This is a grounded answer based on the provided document. [S1]", Usage(
            input_tokens=1700, output_tokens=100
        )


class StubJudge(LLM):
    """₹0 offline stub judge for dry-run validation."""

    model_id = "stub-judge"

    def complete(self, system: str, user: str, *, max_tokens: int) -> tuple[str, Usage]:
        return (
            json.dumps(
                {
                    "claims": [{"text": "factual assertion", "supported": True}],
                    "correctness": "correct",
                    "relevant": True,
                }
            ),
            Usage(input_tokens=500, output_tokens=50),
        )


def compute_split(qid: str) -> str:
    """Deterministic hash split: SHA256(id)[:8] % 2 == 0 -> dev, else test."""
    val = int(hashlib.sha256(qid.encode("utf-8")).hexdigest()[:8], 16)
    return "dev" if (val % 2 == 0) else "test"


def get_git_commit() -> str:
    try:
        git_bin = "/usr/bin/git"
        return (
            subprocess.check_output(  # noqa: S603
                [git_bin, "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="DocuMind End-to-End Evaluation Runner")
    parser.add_argument(
        "--set",
        type=Path,
        default=DEFAULT_SET,
        help="Path to evaluation questions JSONL file",
    )
    parser.add_argument(
        "--split",
        choices=["dev", "test", "all"],
        default="dev",
        help="Evaluation dataset split",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help="Model ID for evaluation judge",
    )
    parser.add_argument(
        "--max-usd",
        type=float,
        default=1.00,
        help="Budget guard cap in USD",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Disable LLM judge scoring",
    )
    parser.add_argument(
        "--store",
        choices=["numpy", "chroma"],
        default="numpy",
        help="Vector store implementation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run ₹0 dry-run using stub generator and stub judge",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of questions to evaluate",
    )

    args = parser.parse_args()

    # Load questions
    if not args.set.exists():
        print(f"Question set {args.set} not found.")
        sys.exit(1)

    raw_questions = [
        json.loads(line)
        for line in args.set.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    parsed_qs: list[EvalQuestion] = []
    for r in raw_questions:
        q_split = compute_split(r["id"])
        if args.split != "all" and q_split != args.split:
            continue
        parsed_qs.append(
            EvalQuestion(
                id=r["id"],
                question=r["question"],
                answerable=r.get("answerable", True),
                group=r.get("group", "own"),
                gold_sources=tuple(r.get("gold_sources", ())),
                gold_snippets=tuple(r.get("gold_snippets", ())),
                reference_answer=r.get("reference_answer"),
            )
        )

    if args.limit:
        parsed_qs = parsed_qs[: args.limit]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / ts
    throwaway_home = run_dir / "home"
    throwaway_home.mkdir(parents=True, exist_ok=True)

    settings = dataclasses.replace(Settings(), home=throwaway_home)
    embedder = SentenceTransformerEmbedder(model_id=settings.embed_model)

    if args.store == "chroma":
        store = ChromaStore(throwaway_home / "chroma", embedder.model_id, embedder.dim)
    else:
        store = NumpyStore(dim=embedder.dim)

    # Index corpus articles
    print(f"Indexing corpus into throwaway home {throwaway_home}...")
    corpus_roots = [CORPUS_DIR, OWN_CORPUS_DIR]
    indexed_files = 0
    for root in corpus_roots:
        if root.exists():
            for fpath in root.glob("*.md"):
                index_path(fpath, root, embedder, store, settings)
                indexed_files += 1
    print(f"Indexed {indexed_files} documents ({store.count()} chunks) in throwaway index.")

    # Configure generator and judge
    if args.dry_run:
        generator: LLM | None = StubGenerator()
        judge_llm: LLM | None = StubJudge() if not args.no_judge else None
        judge_model = "stub-judge"
    else:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY is required for live eval runs.")
            sys.exit(1)
        generator = AnthropicLLM(
            model=settings.model,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_retries,
            api_key=api_key,
        )
        judge_model = (
            args.judge_model or os.getenv("DOCUMIND_JUDGE_MODEL") or "claude-haiku-4-5-20251001"
        )
        judge_llm = (
            AnthropicLLM(
                model=judge_model,
                timeout_s=settings.llm_timeout_s,
                max_retries=settings.llm_retries,
                api_key=api_key,
            )
            if not args.no_judge
            else None
        )

    engine = DocuMind(settings, embedder, store, generator)

    gen_name = getattr(generator, "model_id", "None")
    judge_name = judge_model if not args.no_judge else "None"
    print(
        f"Starting evaluation run: split={args.split}, n={len(parsed_qs)}, "
        f"generator={gen_name}, judge={judge_name}"
    )

    try:
        results = run_e2e(
            engine=engine,
            judge_llm=judge_llm,
            judge_model=judge_model,
            questions=parsed_qs,
            max_usd=args.max_usd,
            judge=not args.no_judge,
        )
    except BudgetExceeded as exc:
        print(f"WARNING: Budget exceeded! {exc}")
        results = exc.results

    summary = summarize(results)

    # Write results.jsonl
    results_file = run_dir / "results.jsonl"
    with results_file.open("w", encoding="utf-8") as f:
        for r in results:
            rec = {
                "id": r.q.id,
                "question": r.q.question,
                "outcome": r.answer.outcome,
                "abstain_reason": r.answer.abstain_reason,
                "answer_text": r.answer.text,
                "citations": [
                    {
                        "marker": c.marker,
                        "source": c.source,
                        "chunk_index": c.chunk_index,
                        "score": c.score,
                    }
                    for c in r.answer.citations
                ],
                "gold_flags": r.gold_flags,
                "citation_gold": r.citation_gold,
                "verdict": dataclasses.asdict(r.verdict) if r.verdict else None,
                "judge_error": r.judge_error,
                "gen_cost_usd": r.gen_cost_usd,
                "judge_cost_usd": r.judge_cost_usd,
            }
            f.write(json.dumps(rec) + "\n")
    print(f"Saved {len(results)} question results to {results_file}")

    # Generate Report Table
    gates = [
        ("Recall@5", summary["recall@5"], 0.85, ">="),
        ("MRR@10", summary["mrr@10"], 0.65, ">="),
        ("Faithfulness", summary["faithfulness_mean"], 0.90, ">="),
        ("Correctness", summary["correctness_mean"], 0.80, ">="),
        ("False-Abstain Rate", summary["false_abstain_rate"], 0.10, "<="),
        (
            "Off-Topic Abstain Rate",
            summary["abstain_rate_by_group"].get("offtopic"),
            0.90,
            ">=",
        ),
        (
            "SQuAD Impossible Abstain Rate",
            summary["abstain_rate_by_group"].get("squad_impossible"),
            0.60,
            ">=",
        ),
        (
            "Citation Precision",
            summary["citation_precision"],
            0.85,
            ">=",
        ),
        (
            "Latency (p95 ms)",
            summary["latency_p95_ms"],
            8000.0,
            "<=",
        ),
        (
            "Generation Cost / Query",
            summary["gen_cost_per_query_usd"],
            0.005,
            "<=",
        ),
    ]

    print("\n=== EVALUATION REPORT ===")
    print(f"Run Metadata: Git={get_git_commit()} | Date={ts} | Split={args.split}")
    print(
        f"Prompt={PROMPT_VERSION} | Judge={JUDGE_VERSION} | "
        f"Gen={settings.model} | JudgeModel={judge_model}\n"
    )

    rep_header = f"{'Metric':<30} | {'Value':<8} | {'Target Gate':<12} | {'Status':<6}"
    print(rep_header)
    print("-" * len(rep_header))

    n_ans = summary["n_answerable"]
    n_unans = summary["n_unanswerable"]
    report_lines: list[str] = [
        f"## Evaluation Report — Split `{args.split}` ({ts})",
        f"- **Git Commit:** `{get_git_commit()}`",
        f"- **Generator Model:** `{settings.model}` (Prompt: `{PROMPT_VERSION}`)",
        f"- **Judge Model:** `{judge_model}` (Judge Version: `{JUDGE_VERSION}`)",
        (
            f"- **Total Questions Evaluated:** {summary['n_total']} "
            f"(Answerable: {n_ans}, Unanswerable: {n_unans})"
        ),
        "",
        "| Metric | Measured Value | Target Gate | Status |",
        "|---|---|---|---|",
    ]

    for name, val, threshold, op in gates:
        if val is None:
            val_str = "n/a"
            status = "SKIP"
        else:
            val_str = (
                f"${val:.5f}"
                if "Cost" in name
                else f"{val:.3f}"
                if isinstance(val, float)
                else str(val)
            )
            passed = (val >= threshold) if op == ">=" else (val <= threshold)
            status = "PASS" if passed else "FAIL"

        print(f"{name:<30} | {val_str:<8} | {op} {threshold:<9} | {status:<6}")
        report_lines.append(f"| **{name}** | {val_str} | {op} {threshold} | **{status}** |")

    # Save REPORT.md in run directory
    (run_dir / "REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")


if __name__ == "__main__":
    main()
