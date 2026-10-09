"""tests/test_citations.py -- citation parser contract tests."""

from __future__ import annotations

from documind.core.citations import is_decline, parse_citations
from documind.core.prompt import DECLINE_SENTINEL
from documind.core.types import Chunk, RetrievedChunk

MARKERS = {
    f"S{i}": RetrievedChunk(Chunk(f"a.md_chunk_{i:04d}", f"text {i}", "a.md", i, "sha"), 0.9, i)
    for i in (1, 2, 3)
}


def test_adjacent_markers_are_all_kept():
    r = parse_citations("A [S1][S2] b [S3].", MARKERS)
    assert r.text == "A [S1][S2] b [S3]." and [c.marker for c in r.citations] == ["S1", "S2", "S3"]
    assert r.invalid == 0


def test_comma_form_is_normalised_to_separate_brackets():
    r = parse_citations("A [S1, S2] b.", MARKERS)
    assert r.text == "A [S1][S2] b." and [c.marker for c in r.citations] == ["S1", "S2"]


def test_repeated_marker_yields_one_citation_in_first_seen_order():
    r = parse_citations("[S2] x [S1] y [S2]", MARKERS)
    assert [c.marker for c in r.citations] == ["S2", "S1"]


def test_unknown_markers_are_removed_and_counted():
    r = parse_citations("A [S1, S7] b [S8].", MARKERS)
    assert [c.marker for c in r.citations] == ["S1"] and r.invalid == 2
    assert "S7" not in r.text and "S8" not in r.text


def test_lookalikes_are_not_markers():
    for text in ("A [s1] b.", "A [S 1] b.", "A (S1) b.", "see S1 b."):
        r = parse_citations(text, MARKERS)
        assert r.citations == () and r.invalid == 0 and r.text == text


def test_citation_fields_come_from_the_retrieved_chunk():
    c = parse_citations("x [S2]", MARKERS).citations[0]
    assert (c.source, c.chunk_index, c.snippet, c.score) == ("a.md", 2, "text 2", 0.9)


def test_decline_detection_is_strict():
    assert is_decline(DECLINE_SENTINEL) and is_decline("  " + DECLINE_SENTINEL + "\n")
    assert not is_decline("Sure. " + DECLINE_SENTINEL)
