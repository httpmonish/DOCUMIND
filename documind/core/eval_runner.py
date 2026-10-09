"""documind/core/eval_runner.py
End-to-end evaluation harness, question execution pipeline, and summary metrics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from documind.core.errors import DocuMindError
from documind.core.eval_judge import (
    JudgeParseError,
    JudgeVerdict,
    build_judge_prompt,
    correctness_score,
    faithfulness,
    parse_judge_output,
)
from documind.core.eval_metrics import (
    is_gold,
    mrr_at_k,
    percentile,
    recall_at_k,
)
from documind.core.pipeline import DocuMind
from documind.core.pricing import cost_usd
from documind.core.types import LLM, Answer


class BudgetExceeded(DocuMindError):
    """Raised when evaluation expenses reach or exceed the allocated max_usd cap."""

    def __init__(self, spent: float, results: list[QuestionResult]) -> None:
        super().__init__(
            f"Evaluation budget exceeded: spent ${spent:.6f}, completed {len(results)} questions."
        )
        self.spent = spent
        self.results = results


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    id: str
    question: str
    answerable: bool
    group: str
    gold_sources: tuple[str, ...] = ()
    gold_snippets: tuple[str, ...] = ()
    reference_answer: str | None = None


@dataclass(frozen=True, slots=True)
class QuestionResult:
    q: EvalQuestion
    answer: Answer
    gold_flags: tuple[bool, ...]
    citation_gold: tuple[bool, ...]
    verdict: JudgeVerdict | None
    judge_error: str | None
    gen_cost_usd: float
    judge_cost_usd: float


def run_e2e(
    engine: DocuMind,
    judge_llm: LLM | None,
    judge_model: str,
    questions: Sequence[EvalQuestion],
    *,
    max_usd: float,
    judge: bool = True,
) -> list[QuestionResult]:
    """Execute evaluation across questions with budget guards and optional judging."""
    results: list[QuestionResult] = []
    spent = 0.0

    for q in questions:
        if spent >= max_usd:
            raise BudgetExceeded(spent, results)

        ans = engine.answer(q.question, interface="eval")
        gen_cost = cost_usd(ans.model, ans.usage) or 0.0

        # Compute gold flags over retrieved chunks
        gold_flags = tuple(
            is_gold(rc.chunk.source, rc.chunk.text, q.gold_sources, q.gold_snippets)
            for rc in ans.retrieved
        )

        # Map citations back to retrieved chunks
        chunk_lookup = {(rc.chunk.source, rc.chunk.chunk_index): rc for rc in ans.retrieved}
        cit_gold_list: list[bool] = []
        for c in ans.citations:
            match_rc = chunk_lookup.get((c.source, c.chunk_index))
            if match_rc:
                cit_gold_list.append(
                    is_gold(
                        match_rc.chunk.source,
                        match_rc.chunk.text,
                        q.gold_sources,
                        q.gold_snippets,
                    )
                )
            else:
                cit_gold_list.append(False)
        citation_gold = tuple(cit_gold_list)

        verdict: JudgeVerdict | None = None
        judge_error: str | None = None
        judge_cost = 0.0

        if judge and judge_llm is not None and q.answerable and ans.outcome == "answered":
            system, user = build_judge_prompt(
                q.question,
                ans.text,
                ans.retrieved,
                q.reference_answer,
            )
            raw_judge, judge_usage = judge_llm.complete(system, user, max_tokens=600)
            judge_cost = cost_usd(judge_model, judge_usage) or 0.0
            try:
                verdict = parse_judge_output(raw_judge)
            except JudgeParseError as err:
                verdict = None
                judge_error = str(err)

        spent += gen_cost + judge_cost

        results.append(
            QuestionResult(
                q=q,
                answer=ans,
                gold_flags=gold_flags,
                citation_gold=citation_gold,
                verdict=verdict,
                judge_error=judge_error,
                gen_cost_usd=gen_cost,
                judge_cost_usd=judge_cost,
            )
        )

    return results


def summarize(results: Sequence[QuestionResult]) -> dict[str, Any]:
    """Compute benchmark summary metrics according to fixed evaluation definitions."""
    n_total = len(results)
    answerable_res = [r for r in results if r.q.answerable]
    unanswerable_res = [r for r in results if not r.q.answerable]

    n_ans = len(answerable_res)
    n_unans = len(unanswerable_res)

    # Retrieval metrics: answerable questions with a gold label
    gold_labeled_res = [r for r in answerable_res if r.q.gold_snippets or r.q.gold_sources]
    if gold_labeled_res:
        flags_matrix = [list(r.gold_flags) for r in gold_labeled_res]
        r5 = recall_at_k(flags_matrix, 5)
        mrr = mrr_at_k(flags_matrix, 10)
    else:
        r5 = None
        mrr = None

    # False-abstain rate: answerable questions that abstained ÷ answerable questions
    if n_ans > 0:
        false_abstains = sum(1 for r in answerable_res if r.answer.outcome == "abstained")
        false_abstain_rate = float(false_abstains / n_ans)
    else:
        false_abstain_rate = None

    # Abstain rate by unanswerable group
    abstain_rate_by_group: dict[str, float] = {}
    groups: dict[str, list[QuestionResult]] = {}
    for r in unanswerable_res:
        groups.setdefault(r.q.group, []).append(r)

    for grp, grp_list in groups.items():
        abstained_count = sum(1 for r in grp_list if r.answer.outcome == "abstained")
        abstain_rate_by_group[grp] = float(abstained_count / len(grp_list))

    # Judge metrics
    faith_scores: list[float] = []
    correct_scores: list[float] = []
    relevance_flags: list[bool] = []
    judge_errors_count = 0

    for r in results:
        if r.judge_error is not None:
            judge_errors_count += 1
        if r.verdict is not None:
            f = faithfulness(r.verdict)
            if f is not None:
                faith_scores.append(f)
            correct_scores.append(correctness_score(r.verdict.correctness))
            relevance_flags.append(r.verdict.relevant)

    faith_n = len(faith_scores)
    faith_mean = float(sum(faith_scores) / faith_n) if faith_n > 0 else None
    correct_mean = float(sum(correct_scores) / len(correct_scores)) if correct_scores else None
    rel_rate = (
        float(sum(1 for rf in relevance_flags if rf) / len(relevance_flags))
        if relevance_flags
        else None
    )

    # Citation precision: cited chunks that are gold ÷ all cited chunks
    total_cited = 0
    total_cited_gold = 0
    for r in gold_labeled_res:
        total_cited += len(r.citation_gold)
        total_cited_gold += sum(1 for is_g in r.citation_gold if is_g)

    citation_precision = float(total_cited_gold / total_cited) if total_cited > 0 else None

    # Latencies
    latencies = [float(r.answer.latency_ms) for r in results]
    lat_p50 = percentile(latencies, 50) if latencies else None
    lat_p95 = percentile(latencies, 95) if latencies else None

    # Costs
    gen_costs = [r.gen_cost_usd for r in results]
    gen_cost_per_query = float(sum(gen_costs) / n_total) if n_total > 0 else None
    judge_cost_total = float(sum(r.judge_cost_usd for r in results))

    return {
        "n_total": n_total,
        "n_answerable": n_ans,
        "n_unanswerable": n_unans,
        "recall@5": r5,
        "mrr@10": mrr,
        "false_abstain_rate": false_abstain_rate,
        "abstain_rate_by_group": abstain_rate_by_group,
        "faithfulness_mean": faith_mean,
        "faithfulness_n": faith_n,
        "correctness_mean": correct_mean,
        "relevance_rate": rel_rate,
        "judge_errors": judge_errors_count,
        "citation_precision": citation_precision,
        "latency_p50_ms": lat_p50,
        "latency_p95_ms": lat_p95,
        "gen_cost_per_query_usd": gen_cost_per_query,
        "judge_cost_total_usd": judge_cost_total,
    }
