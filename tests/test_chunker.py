import pytest

from documind.core.chunker import chunk_document, chunk_text


def test_chunk_size_non_positive_raises_value_error():
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("hello world", chunk_size=0, overlap=0)

    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("hello world", chunk_size=-1, overlap=0)


def test_negative_overlap_raises_value_error():
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("hello world", chunk_size=10, overlap=-5)


def test_overlap_greater_or_equal_chunk_size_raises_value_error():
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("hello world", chunk_size=10, overlap=10)

    with pytest.raises(ValueError, match="overlap"):
        chunk_text("hello world", chunk_size=10, overlap=15)


def test_empty_or_whitespace_text_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_text_shorter_than_chunk_size_returns_single_chunk():
    text = "one two three four five"
    chunks = chunk_text(text, chunk_size=10, overlap=2)
    assert chunks == [text]


def test_201_words_produces_two_chunks_with_expected_sizes():
    words = [f"word{i}" for i in range(201)]
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size=200, overlap=30)
    assert len(chunks) == 2
    assert len(chunks[0].split()) == 200
    assert len(chunks[1].split()) == 31


def test_no_word_is_ever_dropped():
    sample_texts = [
        " ".join([f"w{i}" for i in range(40)]),
        " ".join([f"item_{i}" for i in range(250)]),
        "alpha beta gamma delta epsilon zeta eta theta iota kappa",
    ]
    for text in sample_texts:
        words = text.split()
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        reconstructed_words = " ".join(chunks).split()
        assert set(words) == set(reconstructed_words)


def test_chunk_document_id_formatting_and_metadata():
    doc = {"source": "notes.md", "text": "hello world from documind chunker"}
    chunks = chunk_document(doc, chunk_size=3, overlap=1)
    assert len(chunks) > 0
    for i, c in enumerate(chunks):
        assert c["id"] == f"notes.md_chunk_{i:04d}"
        assert c["source"] == "notes.md"
        assert c["chunk_index"] == i
        assert isinstance(c["text"], str)


def test_chunk_document_missing_source_raises_key_error():
    with pytest.raises(KeyError):
        chunk_document({"text": "hello without source"})
