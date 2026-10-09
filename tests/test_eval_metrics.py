"""tests/test_eval_metrics.py -- contract for documind/core/eval_metrics.py."""

from __future__ import annotations

import random

import numpy as np
import pytest

from documind.core.eval_metrics import (
    agreement,
    cohens_kappa,
    is_gold,
    mrr_at_k,
    normalise,
    paired_bootstrap_ci,
    percentile,
    pick_threshold,
    recall_at_k,
    threshold_sweep,
    wilson_interval,
)


def test_normalise_lowercases_and_collapses_whitespace():
    assert normalise("  Hello \n\tWORLD  ") == "hello world"


def test_is_gold_needs_source_and_snippet_after_normalisation():
    text = "The  Semaphore\nis an integer counter."
    assert is_gold("os.md", text, ["os.md"], ["semaphore is an integer"])
    assert not is_gold("other.md", text, ["os.md"], ["semaphore is an integer"])  # wrong source
    assert not is_gold("os.md", text, ["os.md"], ["mutex"])  # snippet absent
    assert is_gold("any.md", text, [], ["integer counter"])  # no source constraint
    assert not is_gold("os.md", text, ["os.md"], ["", "   "])  # blank snippets never match


def test_recall_and_mrr_on_a_hand_computed_example():
    flags = [
        [False, True, False],
        [True, False, False],
        [False, False, False],
        [False, False, True],
    ]
    assert recall_at_k(flags, 1) == pytest.approx(0.25)
    assert recall_at_k(flags, 2) == pytest.approx(0.5)
    assert recall_at_k(flags, 3) == pytest.approx(0.75)
    assert mrr_at_k(flags, 3) == pytest.approx((1 / 2 + 1 + 0 + 1 / 3) / 4)
    assert mrr_at_k(flags, 1) == pytest.approx(0.25)


@pytest.mark.parametrize(
    "bad",
    [
        [],
    ],
)
def test_recall_and_mrr_reject_empty_input(bad):
    with pytest.raises(ValueError):
        recall_at_k(bad, 5)
    with pytest.raises(ValueError):
        mrr_at_k(bad, 5)


def test_k_must_be_positive():
    with pytest.raises(ValueError):
        recall_at_k([[True]], 0)


def test_percentile_matches_numpy_linear_interpolation():
    values = [3, 1, 4, 1, 5, 9, 2, 6]
    for p in (0, 25, 50, 95, 100):
        assert percentile(values, p) == pytest.approx(float(np.percentile(values, p)))
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1], 101)


def test_wilson_interval_known_values_and_edges():
    lo, hi = wilson_interval(85, 100)
    assert (lo, hi) == (pytest.approx(0.7672, abs=1e-3), pytest.approx(0.9069, abs=1e-3))
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson_interval(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=1e-3)
    lo40, hi40 = wilson_interval(34, 40)  # same 0.85 score, n = 40 -> much wider than n = 200
    lo200, hi200 = wilson_interval(170, 200)
    assert (hi40 - lo40) > 2 * (hi200 - lo200) * 0.9
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_threshold_sweep_and_pick():
    on = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.9, 0.8, 0.7]
    off = [0.5, 0.4, 0.3, 0.2, 0.1]
    rows = threshold_sweep(on, off, [0.2, 0.35, 0.5, 0.65])
    assert rows[1] == {
        "tau": 0.35,
        "false_abstain": pytest.approx(0.1),
        "abstain_rate": pytest.approx(0.6),
    }
    assert pick_threshold(rows, max_false_abstain=0.10) == 0.35
    assert pick_threshold(rows, max_false_abstain=-1.0) is None


def test_paired_bootstrap_ci_properties():
    assert paired_bootstrap_ci([0.0] * 50, [1.0] * 50) == (1.0, 1.0, 1.0)  # b strictly better
    assert paired_bootstrap_ci([1.0] * 30, [1.0] * 30) == (0.0, 0.0, 0.0)  # identical
    r = random.Random(1)  # noqa: S311
    a = [float(r.random() < 0.8) for _ in range(100)]
    b = [float(r.random() < 0.8) for _ in range(100)]
    mean, lo, hi = paired_bootstrap_ci(a, b)
    assert lo <= mean <= hi and lo < 0 < hi  # same-quality systems: CI spans 0
    assert paired_bootstrap_ci(a, b, seed=7) == paired_bootstrap_ci(a, b, seed=7)  # reproducible
    with pytest.raises(ValueError):
        paired_bootstrap_ci([1.0], [1.0, 0.0])


def test_agreement_and_kappa():
    assert agreement([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.75)
    assert cohens_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == pytest.approx(0.5)
    assert cohens_kappa([1, 1], [1, 1]) == 1.0
    with pytest.raises(ValueError):
        agreement([1], [1, 0])


def test_gold_window_centres_clips_and_validates():
    from documind.core.eval_metrics import gold_window

    ctx = "a b c d e f g h i j k l"  # 'f' starts at character 10
    assert gold_window(ctx, 10, words=4) == "d e f g"
    assert gold_window(ctx, 0, words=4) == "a b c d"  # clipped at the start, still 4 words
    assert gold_window(ctx, len(ctx) - 1, words=4) == "i j k l"  # clipped at the end, still 4 words
    assert gold_window("short text", 6, words=8) == "short text"  # context shorter than the window
    assert (
        gold_window("alpha beta gamma", 8, words=2) == "alpha beta"
    )  # answer_start inside "beta" (char 8): window starts one word before it
    with pytest.raises(ValueError):
        gold_window(ctx, 999)
    with pytest.raises(ValueError):
        gold_window(ctx, 1)  # character 1 is the space after 'a'
