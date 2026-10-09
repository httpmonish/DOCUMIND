"""documind/core/citations.py
Citation parsing, marker normalization, and decline detection.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from documind.core.prompt import DECLINE_SENTINEL
from documind.core.types import Citation, RetrievedChunk

_CITATION_PATTERN = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")


@dataclass(frozen=True, slots=True)
class ParsedAnswer:
    text: str
    citations: tuple[Citation, ...]
    invalid: int


def is_decline(text: str) -> bool:
    """Check if the response begins with the exact decline sentinel after stripping."""
    return text.strip().startswith(DECLINE_SENTINEL)


def parse_citations(text: str, markers: Mapping[str, RetrievedChunk]) -> ParsedAnswer:
    """Parse citation markers from text, normalize [S1, S2] into [S1][S2],

    filter unknown markers, and return citations in first-seen order.
    """
    invalid = 0
    citations: dict[str, Citation] = {}

    def _replace_marker_group(match: re.Match[str]) -> str:
        nonlocal invalid
        inner = match.group(1)
        found_markers = [m.strip() for m in inner.split(",") if m.strip()]
        valid_in_group: list[str] = []

        for m in found_markers:
            if m in markers:
                valid_in_group.append(m)
                if m not in citations:
                    rc = markers[m]
                    citations[m] = Citation(
                        marker=m,
                        source=rc.chunk.source,
                        chunk_index=rc.chunk.chunk_index,
                        snippet=rc.chunk.text[:200],
                        score=rc.score,
                    )
            else:
                invalid += 1

        if not valid_in_group:
            return ""
        return "".join(f"[{m}]" for m in valid_in_group)

    cleaned_text = _CITATION_PATTERN.sub(_replace_marker_group, text)

    return ParsedAnswer(
        text=cleaned_text,
        citations=tuple(citations.values()),
        invalid=invalid,
    )
