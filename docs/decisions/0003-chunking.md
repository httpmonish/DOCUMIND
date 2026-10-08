# 0003. Text Chunking Strategy

## Context
Raw documents range from short summaries to 500-page textbooks. Document text must be segmented into coherent, overlapping chunks suitable for dense vector embedding and LLM prompt context injection.

## Options with numbers
1. **Sentence-level chunking (e.g. NLTK/spaCy)**:
   - High dependency overhead (~100 MB model/tokenizer dependencies).
   - High variance in chunk token lengths; single sentences lack broader context.
2. **Fixed character sliding windows**:
   - Simple, but frequently splits words and technical code identifiers mid-token.
3. **Word window (200 words, 30 words overlap)** (Chosen):
   - Zero external NLP dependencies (`text.split()`).
   - Produces p50 token lengths of **266 tokens**, max **322 tokens** on realistic technical text.
   - Guaranteed word preservation across chunk boundaries (`set(words) == set(reconstructed)`).
   - Strict input validation prevents non-positive sizes and negative overlaps.

## Decision
Retain word-based chunking with default `chunk_size = 200` words and `overlap = 30` words. Each chunk receives a deterministic padded ID `f"{source}_chunk_{i:04d}"` and metadata `{source, chunk_index, doc_sha256}`.

## You give up X to get Y
You give up semantic boundary awareness (sentence/paragraph splits) to get **zero external dependencies, deterministic chunk counts, and guaranteed token safety within BGE-Small's 512-token limit**.

## Revisit when
Phase 3 evaluation benchmarks reveal citations cut across sentence boundaries in ways that degrade answer quality.
