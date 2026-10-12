"""documind/core/condense.py
Follow-up query condensation pipeline.
Rewrites ambiguous multi-turn follow-up questions into standalone queries
for effective dense retrieval against vector storage.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from documind.core.types import LLM

logger = logging.getLogger(__name__)

# Pronouns and referring phrases indicating anaphora
_FOLLOW_UP_SIGNALS = {
    "it",
    "its",
    "they",
    "them",
    "their",
    "this",
    "that",
    "these",
    "those",
    "former",
    "latter",
    "above",
    "same",
    "again",
    "also",
    "else",
}

_FOLLOW_UP_PHRASES = (
    "what about",
    "how about",
    "tell me more",
    "explain further",
    "why is that",
    "how does that",
    "how does it",
    "why does it",
    "can you elaborate",
    "what does it do",
    "how so",
)


def is_follow_up_query(question: str, history: Sequence[dict[str, str]]) -> bool:
    """Determine whether an incoming question depends on dialog context."""
    if not history:
        return False

    q_lower = question.strip().lower()
    tokens = set(re.findall(r"\b[a-z]+\b", q_lower))

    # Signal 1: common follow-up lead-in phrases
    for phrase in _FOLLOW_UP_PHRASES:
        if q_lower.startswith(phrase):
            return True

    # Signal 2: contains anaphoric pronouns
    if tokens & _FOLLOW_UP_SIGNALS:
        return True

    # Signal 3: very brief query with existing history
    return bool(len(tokens) <= 4 and history)


def heuristic_condense(question: str, history: Sequence[dict[str, str]]) -> str:
    """Deterministic heuristic condensation by binding the last user topic."""
    if not history:
        return question

    # Extract last user query
    last_user_turn = ""
    for turn in reversed(history):
        if turn.get("role") == "user":
            last_user_turn = turn.get("content", "")
            break

    if not last_user_turn:
        return question

    # Extract salient keywords from last user query
    clean_prev = re.sub(
        r"\b(?:what|why|how|when|where|who|is|are|the|a|an|does|do|can|explain|describe)\b",
        "",
        last_user_turn,
        flags=re.IGNORECASE,
    ).strip()
    topic = " ".join(clean_prev.split()[:4])

    if not topic:
        return question

    q_lower = question.lower()
    # Replace common pronouns with the topic
    condensed = re.sub(r"\b(?:it|this|that)\b", topic, question, flags=re.IGNORECASE)
    if condensed.lower() == q_lower:
        # If no direct pronoun was replaced, append context topic
        condensed = f"{question.rstrip('?')} regarding {topic}?"

    return condensed


def condense_query(
    question: str,
    history: Sequence[dict[str, str]],
    llm: LLM | None = None,
) -> str:
    """Rewrite follow-up question into standalone retrieval query."""
    if not is_follow_up_query(question, history):
        return question

    if llm is None:
        return heuristic_condense(question, history)

    # If LLM is available, perform prompt-based condensation
    turns_text = "\n".join(
        f"{t.get('role', 'user').capitalize()}: {t.get('content', '')}"
        for t in history[-4:]
    )
    system_prompt = (
        "You are a search query reformulation assistant. Given the chat history and a follow-up "
        "question, rewrite the follow-up question into a single self-contained question that "
        "contains all necessary keywords for search. Output ONLY the rephrased question."
    )
    user_prompt = f"Chat History:\n{turns_text}\n\nFollow-up: {question}\n\nStandalone question:"

    try:
        rephrased, _ = llm.complete(system_prompt, user_prompt, max_tokens=60)
        clean = rephrased.strip().strip('"').strip("'")
        if clean and len(clean) >= 4:
            return clean
    except Exception as err:
        logger.warning("LLM query condensation failed (%s), falling back to heuristic", err)

    return heuristic_condense(question, history)
