"""documind/core/eval_metrics.py
Pure metric and statistical functions for retrieval and evaluation harnesses.
"""

from __future__ import annotations

import math
import random
import re
from collections.abc import Sequence
from typing import Any

import numpy as np


def normalise(text: str) -> str:
    """Lowercase text and collapse all contiguous whitespace to single spaces."""
    return " ".join(text.lower().split())


def is_gold(
    chunk_source: str,
    chunk_text: str,
    gold_sources: Sequence[str],
    gold_snippets: Sequence[str],
) -> bool:
    """Return True if chunk matches any allowed gold source and contains any gold snippet."""
    if gold_sources and chunk_source not in gold_sources:
        return False

    norm_chunk = normalise(chunk_text)
    for snippet in gold_snippets:
        norm_snippet = normalise(snippet)
        if norm_snippet and norm_snippet in norm_chunk:
            return True
    return False


def recall_at_k(flags: Sequence[Sequence[bool]], k: int) -> float:
    """Compute Recall@k over a sequence of per-question boolean retrieval flags."""
    if not flags:
        raise ValueError("flags sequence must not be empty")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    hits = sum(1 for row in flags if any(row[:k]))
    return float(hits / len(flags))


def mrr_at_k(flags: Sequence[Sequence[bool]], k: int) -> float:
    """Compute Mean Reciprocal Rank (MRR@k) over per-question ranked boolean flags."""
    if not flags:
        raise ValueError("flags sequence must not be empty")
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")

    reciprocal_ranks: list[float] = []
    for row in flags:
        rr = 0.0
        for rank, flag in enumerate(row[:k], start=1):
            if flag:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

    return float(sum(reciprocal_ranks) / len(reciprocal_ranks))


def percentile(values: Sequence[float], p: float) -> float:
    """Compute percentile using linear interpolation matching numpy.percentile."""
    if not values:
        raise ValueError("values sequence must not be empty")
    if p < 0 or p > 100:
        raise ValueError(f"percentile p must be in [0, 100], got {p}")

    return float(np.percentile(values, p))


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Calculate the Wilson score confidence interval for a binomial proportion."""
    if n <= 0:
        raise ValueError(f"Sample size n must be positive, got {n}")
    if successes < 0 or successes > n:
        raise ValueError(f"Successes must be in [0, {n}], got {successes}")

    p_hat = successes / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denominator
    half_width = (z * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n)))) / denominator

    low = max(0.0, center - half_width)
    high = min(1.0, center + half_width)
    return low, high


def threshold_sweep(
    on_scores: Sequence[float],
    off_scores: Sequence[float],
    taus: Sequence[float],
) -> list[dict[str, float]]:
    """Evaluate false abstention and rejection rates across candidate threshold tau values."""
    if not on_scores:
        raise ValueError("on_scores must not be empty")
    if not off_scores:
        raise ValueError("off_scores must not be empty")

    n_on = len(on_scores)
    n_off = len(off_scores)
    rows: list[dict[str, float]] = []

    for tau in taus:
        false_abstain = sum(1 for s in on_scores if s < tau) / n_on
        abstain_rate = sum(1 for s in off_scores if s < tau) / n_off
        rows.append(
            {
                "tau": float(tau),
                "false_abstain": float(false_abstain),
                "abstain_rate": float(abstain_rate),
            }
        )
    return rows


def pick_threshold(
    rows: Sequence[dict[str, float]],
    max_false_abstain: float = 0.10,
) -> float | None:
    """Select the optimal tau maximizing abstain_rate subject to false_abstain cap."""
    qualified = [r for r in rows if r["false_abstain"] <= max_false_abstain]
    if not qualified:
        return None

    # Maximize abstain_rate, break ties with smallest tau
    qualified.sort(key=lambda r: (-r["abstain_rate"], r["tau"]))
    return qualified[0]["tau"]


def paired_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Compute paired bootstrap confidence interval for the difference (mean(b) - mean(a))."""
    if len(a) != len(b):
        raise ValueError(f"Length mismatch: len(a)={len(a)} != len(b)={len(b)}")
    if not a:
        raise ValueError("Inputs a and b must not be empty")

    n = len(a)
    mean_diff = (sum(b) - sum(a)) / n

    rng = random.Random(seed)  # noqa: S311
    diffs: list[float] = []

    for _ in range(n_boot):
        sample_indices = [rng.randrange(n) for _ in range(n)]
        mean_a = sum(a[i] for i in sample_indices) / n
        mean_b = sum(b[i] for i in sample_indices) / n
        diffs.append(mean_b - mean_a)

    low = percentile(diffs, 100.0 * (alpha / 2.0))
    high = percentile(diffs, 100.0 * (1.0 - alpha / 2.0))
    return mean_diff, low, high


def agreement(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Calculate raw observed agreement fraction between two sequences."""
    if len(a) != len(b):
        raise ValueError(f"Length mismatch: len(a)={len(a)} != len(b)={len(b)}")
    if not a:
        raise ValueError("Sequences must not be empty")

    matches = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    return float(matches / len(a))


def cohens_kappa(a: Sequence[Any], b: Sequence[Any]) -> float:
    """Calculate Cohen's kappa statistic for inter-rater agreement."""
    if len(a) != len(b):
        raise ValueError(f"Length mismatch: len(a)={len(a)} != len(b)={len(b)}")
    if not a:
        raise ValueError("Sequences must not be empty")

    n = len(a)
    po = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n

    classes = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in classes)

    if math.isclose(pe, 1.0, rel_tol=1e-9):
        return 1.0 if math.isclose(po, 1.0, rel_tol=1e-9) else 0.0

    return float((po - pe) / (1.0 - pe))


def gold_window(context: str, answer_start: int, words: int = 8) -> str:
    """Extract a window of `words` words around the word containing character answer_start."""
    if answer_start < 0 or answer_start >= len(context):
        raise ValueError(
            f"answer_start {answer_start} out of range for context length {len(context)}"
        )
    if context[answer_start].isspace():
        raise ValueError(f"answer_start {answer_start} points at whitespace")

    matches = list(re.finditer(r"\S+", context))
    target_idx: int | None = None
    for i, m in enumerate(matches):
        if m.start() <= answer_start < m.end():
            target_idx = i
            break

    if target_idx is None:
        raise ValueError(f"Could not locate word containing answer_start {answer_start}")

    words_list = [m.group() for m in matches]
    n_words = len(words_list)

    if n_words <= words:
        return " ".join(words_list)

    start_idx = target_idx - (words // 2)
    end_idx = start_idx + words

    if start_idx < 0:
        start_idx = 0
        end_idx = words
    elif end_idx > n_words:
        end_idx = n_words
        start_idx = n_words - words

    return " ".join(words_list[start_idx:end_idx])
