"""Unit tests for the deterministic KnowledgeChunker.

The chunker is deterministic: identical input always produces identical
chunks, words are never split when whitespace exists, and no randomness
or ML is involved.
"""

import pytest

from arc.services.chunking import (
    DEFAULT_CHUNK_MAX_CHARS,
    DEFAULT_CHUNK_OVERLAP_CHARS,
    ChunkingConfigurationError,
    ChunkingSettings,
    KnowledgeChunker,
    build_knowledge_chunker,
    get_chunking_settings,
)


class TestKnowledgeChunkerConfig:
    def test_default_config(self):
        """Issue #227: the default overlap is deliberately non-zero."""
        # The class keeps a zero-overlap mechanism default; the non-zero
        # policy is applied at the composition root via ChunkingSettings.
        chunker = KnowledgeChunker()
        assert chunker.max_chars == DEFAULT_CHUNK_MAX_CHARS == 1000
        assert chunker.overlap_chars == 0
        assert DEFAULT_CHUNK_OVERLAP_CHARS > 0
        assert DEFAULT_CHUNK_OVERLAP_CHARS < DEFAULT_CHUNK_MAX_CHARS

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


# ---------------------------------------------------------------------------
# Issue #227: chunking overlap is configured explicitly at the composition
# root, validated, and actually preserves boundary-spanning content.
# ---------------------------------------------------------------------------


def _measured_overlap(first: str, second: str) -> int:
    """Longest suffix of ``first`` that is a prefix of ``second``."""
    for size in range(min(len(first), len(second)), 0, -1):
        if first[-size:] == second[:size]:
            return size
    return 0


class TestChunkingSettings:
    """Environment-driven configuration that fails closed."""

    def test_defaults_when_unset(self, monkeypatch):
        monkeypatch.delenv("KNOWLEDGE_CHUNK_MAX_CHARS", raising=False)
        monkeypatch.delenv("KNOWLEDGE_CHUNK_OVERLAP_CHARS", raising=False)
        settings = get_chunking_settings()
        assert settings.max_chars == DEFAULT_CHUNK_MAX_CHARS
        assert settings.overlap_chars == DEFAULT_CHUNK_OVERLAP_CHARS

    def test_reads_configured_values(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_CHUNK_MAX_CHARS", "500")
        monkeypatch.setenv("KNOWLEDGE_CHUNK_OVERLAP_CHARS", "75")
        settings = get_chunking_settings()
        assert (settings.max_chars, settings.overlap_chars) == (500, 75)

    def test_malformed_max_chars_fails_closed(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_CHUNK_MAX_CHARS", "abc")
        with pytest.raises(ChunkingConfigurationError, match="KNOWLEDGE_CHUNK_MAX_CHARS"):
            get_chunking_settings()

    def test_malformed_overlap_fails_closed(self, monkeypatch):
        monkeypatch.setenv("KNOWLEDGE_CHUNK_MAX_CHARS", "1000")
        monkeypatch.setenv("KNOWLEDGE_CHUNK_OVERLAP_CHARS", "not-a-number")
        with pytest.raises(ChunkingConfigurationError, match="KNOWLEDGE_CHUNK_OVERLAP_CHARS"):
            get_chunking_settings()

    @pytest.mark.parametrize("max_chars", [0, -1])
    def test_non_positive_max_rejected(self, max_chars):
        with pytest.raises(ChunkingConfigurationError, match="KNOWLEDGE_CHUNK_MAX_CHARS"):
            ChunkingSettings(max_chars=max_chars, overlap_chars=0)

    def test_negative_overlap_rejected(self):
        with pytest.raises(ChunkingConfigurationError, match="KNOWLEDGE_CHUNK_OVERLAP_CHARS"):
            ChunkingSettings(max_chars=100, overlap_chars=-1)

    def test_overlap_not_smaller_than_max_rejected(self):
        """Overlap >= max cannot make forward progress."""
        with pytest.raises(ChunkingConfigurationError, match="must be smaller"):
            ChunkingSettings(max_chars=100, overlap_chars=100)

    def test_bool_is_not_an_acceptable_integer(self):
        # isinstance(True, int) is True in Python; a bool must not slip
        # through as a chunk size of 1.
        with pytest.raises(ChunkingConfigurationError):
            ChunkingSettings(max_chars=True, overlap_chars=0)

    def test_build_uses_settings(self):
        chunker = build_knowledge_chunker(ChunkingSettings(max_chars=400, overlap_chars=40))
        assert (chunker.max_chars, chunker.overlap_chars) == (400, 40)


class TestOverlapPreservesBoundaryContent:
    """The reason the overlap exists at all."""

    FACT = "Escalate every severity one incident to the on-call engineer within fifteen minutes."

    def _document(self, offset: int) -> str:
        filler = "Background policy text that pads the document. " * 40
        return filler[:offset] + self.FACT + " " + filler

    @pytest.mark.parametrize("offset", [960, 980])
    def test_boundary_spanning_fact_is_lost_without_overlap(self, offset):
        """Documents the failure the default protects against."""
        chunks = KnowledgeChunker(max_chars=1000, overlap_chars=0).chunk(self._document(offset))
        assert not any(self.FACT in chunk for chunk in chunks)

    @pytest.mark.parametrize("offset", [960, 980, 995])
    def test_boundary_spanning_fact_survives_with_default_overlap(self, offset):
        chunks = build_knowledge_chunker(get_chunking_settings()).chunk(self._document(offset))
        assert any(self.FACT in chunk for chunk in chunks)

    def test_consecutive_chunks_actually_overlap(self):
        content = " ".join(f"word{index:03d}" for index in range(400))
        chunks = KnowledgeChunker(max_chars=200, overlap_chars=50).chunk(content)
        assert len(chunks) > 2
        for first, second in zip(chunks, chunks[1:]):
            assert _measured_overlap(first, second) > 0


class TestOverlapDoesNotDuplicateOrExplode:
    """Overlap adds redundancy, not junk."""

    def test_no_chunk_is_wholly_contained_in_its_predecessor(self):
        # Word lengths close to max_chars used to emit an overlap-only
        # fragment ("ghi") that repeated the previous chunk's tail.
        content = "abcdefghi jklmnopqr stuvwxyz0 123456789"
        chunks = KnowledgeChunker(max_chars=10, overlap_chars=3).chunk(content)
        for first, second in zip(chunks, chunks[1:]):
            assert second not in first

    def test_zero_overlap_behaviour_is_unchanged(self):
        content = " ".join(f"token{index:04d}" for index in range(500))
        chunks = KnowledgeChunker(max_chars=1000, overlap_chars=0).chunk(content)
        # Reassembling zero-overlap chunks reproduces the original words.
        assert " ".join(chunks).split() == content.split()

    def test_chunk_growth_is_bounded(self):
        content = " ".join(f"token{index:04d}" for index in range(4000))
        baseline = len(KnowledgeChunker(max_chars=1000, overlap_chars=0).chunk(content))
        with_overlap = len(build_knowledge_chunker(get_chunking_settings()).chunk(content))
        # Redundancy costs chunks, but must not multiply them.
        assert baseline < with_overlap < baseline * 1.5

    def test_every_chunk_respects_max_chars(self):
        content = " ".join(f"word{index:03d}" for index in range(600))
        for chunk in KnowledgeChunker(max_chars=200, overlap_chars=50).chunk(content):
            assert len(chunk) <= 200
