"""Unit tests for the deterministic KnowledgeChunker.

The chunker is deterministic: identical input always produces identical
chunks, words are never split when whitespace exists, and no randomness
or ML is involved.
"""

import pytest

from arc.services.chunking import KnowledgeChunker


class TestKnowledgeChunkerConfig:
    def test_default_config(self):
        chunker = KnowledgeChunker()
        assert chunker.max_chars == 1000
        assert chunker.overlap_chars == 0

    def test_max_chars_must_be_positive(self):
        with pytest.raises(ValueError):
            KnowledgeChunker(max_chars=0)
        with pytest.raises(ValueError):
            KnowledgeChunker(max_chars=-5)

    def test_overlap_chars_must_be_non_negative_and_smaller_than_max_chars(self):
        with pytest.raises(ValueError):
            KnowledgeChunker(overlap_chars=-1)
        with pytest.raises(ValueError):
            KnowledgeChunker(max_chars=10, overlap_chars=10)


class TestKnowledgeChunkerBehavior:
    def test_empty_and_whitespace_content_produce_no_chunks(self):
        assert KnowledgeChunker().chunk("") == []
        assert KnowledgeChunker().chunk("   ") == []

    def test_content_within_max_chars_returns_single_chunk(self):
        chunker = KnowledgeChunker(max_chars=1000)
        content = "Approved remote work policy."
        assert chunker.chunk(content) == [content]

    def test_content_is_cut_at_word_boundaries(self):
        chunker = KnowledgeChunker(max_chars=10)
        # Chunks are cut at the last whitespace within each window; a
        # remainder that fits is kept as one final chunk.
        assert chunker.chunk("one two three four five") == ["one two", "three", "four five"]

    def test_exact_boundary_does_not_split(self):
        assert KnowledgeChunker(max_chars=5).chunk("abcde") == ["abcde"]
        # The space sits exactly at the boundary: both words stay intact.
        assert KnowledgeChunker(max_chars=6).chunk("abcde fghij") == ["abcde", "fghij"]

    def test_hard_cut_when_content_has_no_whitespace(self):
        chunker = KnowledgeChunker(max_chars=4)
        assert chunker.chunk("abcdefghij") == ["abcd", "efgh", "ij"]

    def test_long_content_is_fully_consumed(self):
        chunker = KnowledgeChunker(max_chars=7)
        content = "the quick brown fox jumps over the lazy dog"
        chunks = chunker.chunk(content)
        assert "".join(chunks).replace(" ", "") == content.replace(" ", "")
        assert len(chunks) >= 3

    def test_overlap_repeats_tail_of_previous_chunk(self):
        chunker = KnowledgeChunker(max_chars=10, overlap_chars=3)
        chunks = chunker.chunk("one two three four five")
        assert chunks == ["one two", "two three", "ree four", "our five"]
        # Overlap invariant: the first overlap_chars of every chunk equal
        # the last overlap_chars of the previous chunk.
        for previous, current in zip(chunks, chunks[1:]):
            assert previous[-3:] == current[:3]

    def test_deterministic(self):
        chunker = KnowledgeChunker(max_chars=12)
        content = "deterministic chunking must never vary between calls"
        assert chunker.chunk(content) == chunker.chunk(content)
