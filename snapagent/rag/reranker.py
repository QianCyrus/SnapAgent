"""Lightweight cross-encoder reranking via FlashRank.

Falls back to keyword-overlap scoring when FlashRank is not installed.
Install for enhanced reranking: ``pip install flashrank``
"""

from __future__ import annotations

import re
from typing import Any


class Reranker:
    """Reranks document chunks by relevance using FlashRank or keyword fallback."""

    def __init__(self, model_name: str = "ms-marco-MiniLM-L-12-v2"):
        self._model_name = model_name
        self._ranker: Any = None
        self._available: bool | None = None

    def rerank(self, query: str, chunks: list[str], *, top_k: int = 5) -> list[str]:
        """Rerank chunks by relevance to the query.

        Args:
            query: The search query.
            chunks: Text chunks to rank.
            top_k: Maximum chunks to return.

        Returns:
            Top-K chunks sorted by descending relevance.
        """
        if not chunks:
            return []
        top_k = min(top_k, len(chunks))

        if self._ensure_ranker():
            return self._flashrank_rerank(query, chunks, top_k)
        return self._keyword_rerank(query, chunks, top_k)

    def _ensure_ranker(self) -> bool:
        """Lazily initialise FlashRank. Returns True if available."""
        if self._available is not None:
            return self._available
        try:
            from flashrank import Ranker

            self._ranker = Ranker(model_name=self._model_name)
            self._available = True
        except (ImportError, Exception):
            self._available = False
        return self._available

    def _flashrank_rerank(self, query: str, chunks: list[str], top_k: int) -> list[str]:
        """Rerank with FlashRank cross-encoder."""
        from flashrank import RerankRequest

        passages = [{"text": c} for c in chunks]
        request = RerankRequest(query=query, passages=passages)
        results = self._ranker.rerank(request)
        scored = [
            (
                getattr(r, "text", r.get("text", "") if isinstance(r, dict) else ""),
                getattr(r, "score", r.get("score", 0.0) if isinstance(r, dict) else 0.0),
            )
            for r in results
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [text for text, _ in scored[:top_k]]

    @staticmethod
    def _keyword_rerank(query: str, chunks: list[str], top_k: int) -> list[str]:
        """Fallback: rank by keyword overlap with positional decay."""
        query_terms = set(re.findall(r"\w{2,}", query.lower()))
        if not query_terms:
            return chunks[:top_k]

        scored: list[tuple[str, float]] = []
        for idx, chunk in enumerate(chunks):
            chunk_terms = set(re.findall(r"\w{2,}", chunk.lower()))
            overlap = len(query_terms & chunk_terms) / len(query_terms)
            score = overlap - idx * 0.01
            scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [text for text, _ in scored[:top_k]]
