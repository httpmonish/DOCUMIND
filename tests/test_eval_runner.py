"""tests/test_eval_runner.py -- end-to-end evaluation plumbing, offline
(FakeLLM generator + FakeLLM judge).
"""

from __future__ import annotations

import pytest

from documind.core.eval_runner import BudgetExceeded, EvalQuestion, run_e2e, summarize
from documind.core.vector_store import NumpyStore
from tests.engine_helpers import PAGING_TEXT, SEMAPHORE_TEXT, make_engine
from tests.fake_llm import FakeLLM

JUDGE_OK = '{"claims":[{"text":"x","supported":true}],"correctness":"correct","relevant":true}'
JUDGE_BAD = '{"claims":[{"text":"x","supported":false}],"correctness":"incorrect","relevant":true}'
MODEL = "claude-haiku-4-5-20251001"


class SequencedJudge(FakeLLM):
    def __init__(self, replies):
        super().__init__(replies[0])
        self.replies = list(replies)

    def complete(self, system, user, *, max_tokens):
        self.reply = self.replies[min(len(self.calls), len(self.replies) - 1)]
        return super().complete(system, user, max_tokens=max_tokens)


def _setup(tmp_path):
    eng, llm, emb = make_engine(
        tmp_path, NumpyStore()
    )  # generator always answers "A semaphore is a counter. [S1]"
    emb.script["explain paging"] = PAGING_TEXT
    emb.script["what colour is a semaphore"] = SEMAPHORE_TEXT
    qs = [
        EvalQuestion(
            "q1",
            "what is a semaphore",
            True,
            "own",
            ("os.md",),
            ("semaphore is an integer",),
            "a counter",
        ),
        EvalQuestion(
            "q2",
            "explain paging",
            True,
            "own",
            ("os.md",),
            ("paging divides memory",),
            "frames",
        ),
        EvalQuestion("q3", "who won the 2022 football world cup", False, "offtopic"),
        EvalQuestion("q4", "what colour is a semaphore", False, "squad_impossible"),
    ]
    return eng, qs


def test_summary_matches_hand_computed_numbers(tmp_path):
    eng, qs = _setup(tmp_path)
    judge = SequencedJudge(
        [JUDGE_OK, JUDGE_BAD]
    )  # q1 judged good, q2 judged bad (wrong answer about paging)
    results = run_e2e(eng, judge, MODEL, qs, max_usd=5.0)
    s = summarize(results)
    assert (s["n_total"], s["n_answerable"], s["n_unanswerable"]) == (4, 2, 2)
    assert s["recall@5"] == pytest.approx(1.0) and s["mrr@10"] == pytest.approx(1.0)
    assert s["false_abstain_rate"] == pytest.approx(0.0)
    assert s["abstain_rate_by_group"] == {"offtopic": 1.0, "squad_impossible": 0.0}
    assert s["faithfulness_mean"] == pytest.approx(0.5) and s["faithfulness_n"] == 2
    assert s["correctness_mean"] == pytest.approx(0.5) and s["relevance_rate"] == pytest.approx(1.0)
    assert s["citation_precision"] == pytest.approx(
        1.0
    )  # both cited chunks are gold -- yet q2's answer is wrong:
    assert s["judge_errors"] == 0  # citation precision cannot see that; faithfulness does
    assert s["gen_cost_per_query_usd"] == pytest.approx(3 * 0.0032 / 4)
    assert s["judge_cost_total_usd"] == pytest.approx(2 * 0.0032)
    assert len(judge.calls) == 2  # only answerable + answered questions are judged


def test_unparseable_judge_output_is_counted_not_fatal(tmp_path):
    eng, qs = _setup(tmp_path)
    results = run_e2e(
        eng,
        SequencedJudge(["I refuse to answer in JSON", JUDGE_OK]),
        MODEL,
        qs,
        max_usd=5.0,
    )
    s = summarize(results)
    assert (
        s["judge_errors"] == 1
        and s["faithfulness_n"] == 1
        and s["faithfulness_mean"] == pytest.approx(1.0)
    )


def test_budget_guard_stops_the_run_and_keeps_partial_results(tmp_path):
    eng, qs = _setup(tmp_path)
    with pytest.raises(BudgetExceeded) as exc:
        run_e2e(
            eng,
            SequencedJudge([JUDGE_OK]),
            MODEL,
            qs,
            max_usd=0.005,
        )  # q1 alone costs 0.0064
    assert len(exc.value.results) == 1 and exc.value.spent == pytest.approx(0.0064)


def test_no_judge_mode_makes_zero_judge_calls(tmp_path):
    eng, qs = _setup(tmp_path)
    judge = SequencedJudge([JUDGE_OK])
    s = summarize(run_e2e(eng, judge, MODEL, qs, max_usd=5.0, judge=False))
    assert (
        len(judge.calls) == 0
        and s["faithfulness_mean"] is None
        and s["judge_cost_total_usd"] == 0.0
    )
