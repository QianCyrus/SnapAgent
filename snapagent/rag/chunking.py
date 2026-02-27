"""Semantic text chunking for RAG document processing.

Implements a two-layer strategy:
1. Structural splitting on headers and paragraph boundaries.
2. Percentile-based similarity breakpoint detection for large sections.
"""

from __future__ import annotations

import re
from collections import Counter
from math import sqrt


def semantic_chunk(
    text: str,
    *,
    max_chunk_size: int = 1500,
    min_chunk_size: int = 100,
    percentile: int = 80,
) -> list[str]:
    """Split text into semantically coherent chunks.

    Args:
        text: Input text to chunk.
        max_chunk_size: Maximum characters per chunk.
        min_chunk_size: Minimum characters; smaller chunks get merged.
        percentile: Similarity percentile threshold (0-100) for breakpoints.

    Returns:
        List of text chunks preserving semantic coherence.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chunk_size:
        return [text]

    sections = _split_by_structure(text)

    chunks: list[str] = []
    for section in sections:
        if len(section) <= max_chunk_size:
            chunks.append(section)
        else:
            chunks.extend(_split_by_similarity(section, percentile=percentile))

    chunks = _merge_small(chunks, min_size=min_chunk_size)
    chunks = _split_oversized(chunks, max_size=max_chunk_size)
    return [c for c in chunks if c.strip()]


_STRUCTURAL_RE = re.compile(
    r"(?:"
    r"(?:^|\n)#{1,6}\s+.+|"  # Markdown headers
    r"\n{2,}|"  # Paragraph breaks
    r"(?:^|\n)(?:---+|===+)\s*\n"  # Horizontal rules
    r")",
    re.MULTILINE,
)

_SENTENCE_RE = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")


def _split_by_structure(text: str) -> list[str]:
    """Split text on structural markers (headers, paragraph breaks)."""
    parts = _STRUCTURAL_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = _SENTENCE_RE.split(text)
    return [s.strip() for s in sentences if s.strip()]


def _tokenize(text: str) -> Counter[str]:
    """Bag-of-words tokenizer for similarity computation."""
    return Counter(re.findall(r"\w{2,}", text.lower()))


def _cosine_similarity(a: Counter[str], b: Counter[str]) -> float:
    """Cosine similarity between two word-frequency counters."""
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[w] * b[w] for w in common)
    mag_a = sqrt(sum(v * v for v in a.values()))
    mag_b = sqrt(sum(v * v for v in b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _split_by_similarity(
    text: str,
    *,
    percentile: int = 80,
    window: int = 2,
) -> list[str]:
    """Split text where adjacent sentence groups diverge semantically.

    Uses percentile-based threshold on cosine similarity between sliding
    windows of sentences to detect topic transitions.

    Args:
        text: Text section to split.
        percentile: Break at similarity values below this percentile.
        window: Sentences per comparison group.

    Returns:
        List of sub-chunks.
    """
    sentences = _split_sentences(text)
    if len(sentences) <= window * 2:
        return [text]

    similarities: list[float] = []
    for i in range(len(sentences) - window):
        end_b = min(i + window * 2, len(sentences))
        group_a = " ".join(sentences[i : i + window])
        group_b = " ".join(sentences[i + window : end_b])
        similarities.append(_cosine_similarity(_tokenize(group_a), _tokenize(group_b)))

    if not similarities:
        return [text]

    sorted_sims = sorted(similarities)
    threshold_idx = max(0, int(len(sorted_sims) * (1 - percentile / 100)))
    threshold = sorted_sims[threshold_idx]

    breakpoints: list[int] = []
    for i, sim in enumerate(similarities):
        if sim <= threshold:
            bp = i + window
            if not breakpoints or bp > breakpoints[-1] + window:
                breakpoints.append(bp)

    chunks: list[str] = []
    start = 0
    for bp in breakpoints:
        chunk = " ".join(sentences[start:bp]).strip()
        if chunk:
            chunks.append(chunk)
        start = bp
    remaining = " ".join(sentences[start:]).strip()
    if remaining:
        chunks.append(remaining)

    return chunks if chunks else [text]


def _merge_small(chunks: list[str], *, min_size: int) -> list[str]:
    """Merge chunks smaller than min_size into their neighbors."""
    if not chunks:
        return []
    merged: list[str] = [chunks[0]]
    for chunk in chunks[1:]:
        if len(merged[-1]) < min_size:
            merged[-1] = merged[-1] + "\n\n" + chunk
        else:
            merged.append(chunk)
    if len(merged) > 1 and len(merged[-1]) < min_size:
        merged[-2] = merged[-2] + "\n\n" + merged[-1]
        merged.pop()
    return merged


def _split_oversized(chunks: list[str], *, max_size: int) -> list[str]:
    """Split chunks exceeding max_size at sentence boundaries."""
    result: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_size:
            result.append(chunk)
            continue
        sentences = _split_sentences(chunk)
        current: list[str] = []
        current_len = 0
        for sentence in sentences:
            if current and current_len + len(sentence) > max_size:
                result.append(" ".join(current))
                current = []
                current_len = 0
            current.append(sentence)
            current_len += len(sentence) + 1
        if current:
            result.append(" ".join(current))
    return result
