#!/usr/bin/env python3
"""scripts/build_squad_eval.py -- Build retrieval evaluation benchmark from SQuAD 2.0 dev."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from documind.core.eval_metrics import gold_window, normalise

SQUAD_FILE = Path(__file__).parent.parent / "evals" / "data" / "dev-v2.0.json"
CORPUS_DIR = Path(__file__).parent.parent / "evals" / "corpus"
RETRIEVAL_SET_FILE = Path(__file__).parent.parent / "evals" / "retrieval_set.jsonl"
IMPOSSIBLE_SET_FILE = Path(__file__).parent.parent / "evals" / "squad_impossible.jsonl"

PRONOUNS = {"he", "she", "it", "they", "him", "her", "them", "his", "its", "their"}


def make_slug(title: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", title).strip("_").lower()


def main() -> None:
    if not SQUAD_FILE.exists():
        raise FileNotFoundError(
            f"SQuAD data missing at {SQUAD_FILE}. Run scripts/fetch_squad.py first."
        )

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    raw_data = json.loads(SQUAD_FILE.read_text(encoding="utf-8"))["data"]

    # 1. Sort titles alphabetically and take the first 10
    raw_data.sort(key=lambda x: x["title"])
    articles = raw_data[:10]

    print("Selected 10 articles in alphabetical order:")
    slug_map: dict[str, str] = {}
    for i, art in enumerate(articles, start=1):
        slug = make_slug(art["title"])
        slug_map[art["title"]] = slug
        print(f"  {i:2d}. {art['title']} -> {slug}.md")

        # Write corpus file: paragraphs separated by blank lines
        paragraphs = [p["context"] for p in art["paragraphs"]]
        corpus_text = "\n\n".join(paragraphs)
        (CORPUS_DIR / f"{slug}.md").write_text(corpus_text, encoding="utf-8")

    # 2. Filter questions and sample 20 answerable per article
    dropped_short = 0
    dropped_pronoun = 0
    dropped_snippet_fail = 0

    all_retrieval_rows: list[dict] = []
    all_impossible_rows: list[dict] = []

    rng = random.Random(42)  # noqa: S311

    for art in articles:
        slug = slug_map[art["title"]]
        slug_file = f"{slug}.md"
        article_text = (CORPUS_DIR / slug_file).read_text(encoding="utf-8")
        norm_article_text = normalise(article_text)

        qualified_qas: list[dict] = []
        impossible_qas: list[dict] = []

        for p in art["paragraphs"]:
            ctx = p["context"]
            for qa in p["qas"]:
                if qa.get("is_impossible", False):
                    impossible_qas.append(qa)
                    continue

                if not qa.get("answers"):
                    continue

                q_text = qa["question"].strip()
                words = [w.strip("?,.!\"'").lower() for w in q_text.split()]

                # Quality Filter Rule 1: minimum length
                if len(words) < 4 or len(q_text) < 15:
                    dropped_short += 1
                    continue

                # Quality Filter Rule 2: ambiguous bare pronoun
                if words and (words[0] in PRONOUNS or (len(words) > 1 and words[1] in PRONOUNS)):
                    dropped_pronoun += 1
                    continue

                # Snippet window extraction
                ans_start = qa["answers"][0]["answer_start"]
                try:
                    snippet = gold_window(ctx, ans_start, words=8)
                except ValueError:
                    dropped_snippet_fail += 1
                    continue

                if normalise(snippet) not in norm_article_text:
                    dropped_snippet_fail += 1
                    continue

                qualified_qas.append(
                    {
                        "id": qa["id"],
                        "question": q_text,
                        "answerable": True,
                        "gold_sources": [slug_file],
                        "gold_snippets": [snippet],
                    }
                )

        # Sort by id ascending and sample 20 deterministically
        qualified_qas.sort(key=lambda x: x["id"])
        if len(qualified_qas) < 20:
            raise ValueError(
                f"Article {art['title']} has only {len(qualified_qas)} questions, expected >= 20"
            )
        sampled = rng.sample(qualified_qas, 20)
        sampled.sort(key=lambda x: x["id"])
        all_retrieval_rows.extend(sampled)

        # One impossible question per article
        if impossible_qas:
            impossible_qas.sort(key=lambda x: x["id"])
            imp_choice = rng.choice(impossible_qas)
            all_impossible_rows.append(
                {
                    "id": imp_choice["id"],
                    "question": imp_choice["question"].strip(),
                    "answerable": False,
                    "group": "squad_impossible",
                    "gold_sources": [slug_file],
                    "gold_snippets": [],
                }
            )

    print("\nQuality Filter Statistics:")
    print(f"  Dropped (too short / <4 words):    {dropped_short}")
    print(f"  Dropped (ambiguous pronoun start): {dropped_pronoun}")
    print(f"  Dropped (snippet extraction fail): {dropped_snippet_fail}")
    print(f"  Total Retrieval Questions:         {len(all_retrieval_rows)} (20 per article)")
    print(f"  Total Impossible Questions:        {len(all_impossible_rows)} (1 per article)")

    # 3. Write output JSONL files
    with RETRIEVAL_SET_FILE.open("w", encoding="utf-8") as f:
        for row in all_retrieval_rows:
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(all_retrieval_rows)} rows to {RETRIEVAL_SET_FILE}")

    with IMPOSSIBLE_SET_FILE.open("w", encoding="utf-8") as f:
        for row in all_impossible_rows:
            f.write(json.dumps(row) + "\n")
    print(f"Wrote {len(all_impossible_rows)} rows to {IMPOSSIBLE_SET_FILE}")


if __name__ == "__main__":
    main()
