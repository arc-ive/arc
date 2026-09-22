"""Deterministic chunking for the Company Brain Secure RAG foundation.

Chunking operates EXCLUSIVELY on already-sanitized knowledge content: the
PII Guard boundary (KnowledgeService) is the only production path that
produces the content this chunker receives. Chunking never receives raw
content and never re-introduces it.

The chunker is deterministic: the same content always produces the same
chunks (no ML, no tokenization, no randomness). Segments are cut at
whitespace boundaries so words are never split, except for content with
no whitespace at all, which is hard-cut at the maximum length.
"""

import os
from dataclasses import dataclass
from typing import List

# Chunking policy defaults (Issue #227).
#
# ``KnowledgeChunker`` itself keeps ``overlap_chars=0`` as its bare
# mechanism default so a caller that asks for a small ``max_chars`` is
# never handed an invalid combination. The POLICY — what production
# actually runs — lives in ``ChunkingSettings`` and is applied at the
# composition root, which is where issue #227 requires it to be explicit.
#
# The overlap is deliberately non-zero: with zero overlap a fact that
# straddles a chunk boundary is split across two chunks with no
# redundancy and can be retrievable from neither half. 150 characters
# spans a typical sentence and costs roughly 15% more chunks at the
# 1000-character default.
DEFAULT_CHUNK_MAX_CHARS = 1000
DEFAULT_CHUNK_OVERLAP_CHARS = 150


class ChunkingConfigurationError(Exception):
    """Raised when chunking configuration is missing or invalid.

    Configuration failures fail closed with an actionable message naming
    the setting, following the same pattern as
    ``EmbeddingConfigurationError`` and ``LlmConfigurationError``.
    """


@dataclass(frozen=True)
class ChunkingSettings:
    """Chunking configuration derived from the environment.

    ``max_chars`` bounds a single chunk. ``overlap_chars`` is the number
    of trailing characters repeated at the start of the next chunk so
    boundary-spanning content stays retrievable. Overlap must be smaller
    than ``max_chars``; equal or larger values cannot make forward
    progress.
    """

    max_chars: int = DEFAULT_CHUNK_MAX_CHARS
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS

    def __post_init__(self) -> None:
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
            raise ChunkingConfigurationError(
                f"KNOWLEDGE_CHUNK_MAX_CHARS must be a positive integer, got {self.max_chars!r}"
            )
        if self.max_chars < 1:
            raise ChunkingConfigurationError(
                f"KNOWLEDGE_CHUNK_MAX_CHARS must be a positive integer, got {self.max_chars!r}"
            )
        if isinstance(self.overlap_chars, bool) or not isinstance(self.overlap_chars, int):
            raise ChunkingConfigurationError(
                "KNOWLEDGE_CHUNK_OVERLAP_CHARS must be a non-negative integer, "
                f"got {self.overlap_chars!r}"
            )
        if self.overlap_chars < 0:
            raise ChunkingConfigurationError(
                "KNOWLEDGE_CHUNK_OVERLAP_CHARS must be a non-negative integer, "
                f"got {self.overlap_chars!r}"
            )
        if self.overlap_chars >= self.max_chars:
            raise ChunkingConfigurationError(
                f"KNOWLEDGE_CHUNK_OVERLAP_CHARS ({self.overlap_chars}) must be smaller "
                f"than KNOWLEDGE_CHUNK_MAX_CHARS ({self.max_chars})"
            )


def _parse_int(raw: str, setting: str) -> int:
    """Parse an integer setting and fail closed on invalid values."""
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ChunkingConfigurationError(f"{setting} must be a valid integer, got {raw!r}") from exc


def get_chunking_settings() -> ChunkingSettings:
    """Build chunking settings from the environment.

    Malformed values fail closed here with a message naming the setting,
    rather than surfacing as an opaque error deep in ingestion.
    """
    return ChunkingSettings(
        max_chars=_parse_int(
            os.getenv("KNOWLEDGE_CHUNK_MAX_CHARS", str(DEFAULT_CHUNK_MAX_CHARS)),
            "KNOWLEDGE_CHUNK_MAX_CHARS",
        ),
        overlap_chars=_parse_int(
            os.getenv("KNOWLEDGE_CHUNK_OVERLAP_CHARS", str(DEFAULT_CHUNK_OVERLAP_CHARS)),
            "KNOWLEDGE_CHUNK_OVERLAP_CHARS",
        ),
    )


def build_knowledge_chunker(settings: ChunkingSettings) -> "KnowledgeChunker":
    """Build the chunker from validated settings (composition root)."""
    return KnowledgeChunker(max_chars=settings.max_chars, overlap_chars=settings.overlap_chars)


class KnowledgeChunker:
    """Deterministic, whitespace-aware chunker for sanitized knowledge content.

    Args:
        max_chars: maximum length of a chunk in characters.
        overlap_chars: number of trailing characters of a chunk repeated
            at the start of the next chunk to preserve context across
            boundaries.

    Raises:
        ValueError: when ``max_chars`` is not positive or ``overlap_chars``
            is negative or not smaller than ``max_chars``.
    """

    def __init__(self, max_chars: int = DEFAULT_CHUNK_MAX_CHARS, overlap_chars: int = 0):
        if max_chars < 1:
            raise ValueError("max_chars must be a positive integer")
        if overlap_chars < 0 or overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, content: str) -> List[str]:
        """Split sanitized content into deterministic text segments.

        Returns an empty list for empty content and a single segment when
        the content fits within ``max_chars``.
        """
        if not content.strip():
            return []

        if len(content) <= self.max_chars:
            return [content]

        chunks: List[str] = []
        start = 0
        length = len(content)
        # Highest original index already represented by an emitted chunk.
        # With overlap the window steps backwards, so a segment ending at
        # or before this point would repeat earlier content while adding
        # nothing new. Such a segment is skipped rather than emitted as a
        # duplicate-only chunk (Issue #227).
        covered_to = 0
        while start < length:
            end = min(start + self.max_chars, length)
            if end == length:
                if end > covered_to:
                    tail = content[start:].strip()
                    if tail:
                        chunks.append(tail)
                break

            cut = content.rfind(" ", start + 1, end + 1)
            if cut <= start:
                cut = end

            if cut > covered_to:
                piece = content[start:cut].strip()
                if piece:
                    chunks.append(piece)
                covered_to = cut

            if self.overlap_chars > 0 and cut - self.overlap_chars > start:
                start = cut - self.overlap_chars
            else:
                start = max(cut, start + 1)
        return chunks
