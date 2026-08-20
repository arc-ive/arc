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

from typing import List


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

    def __init__(self, max_chars: int = 1000, overlap_chars: int = 0):
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
        while start < len(content):
            end = min(start + self.max_chars, len(content))
            if end == len(content):
                tail = content[start:].strip()
                if tail:
                    chunks.append(tail)
                break

            cut = content.rfind(" ", start + 1, end + 1)
            if cut <= start:
                cut = end

            piece = content[start:cut].strip()
            if piece:
                chunks.append(piece)

            if self.overlap_chars > 0 and cut < end and cut - self.overlap_chars > start:
                start = cut - self.overlap_chars
            else:
                start = max(cut, start + 1)
        return chunks
