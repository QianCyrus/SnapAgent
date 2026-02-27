"""RAG pipeline for hallucination-resistant document querying.

Provides semantic chunking, cross-encoder reranking, structured generation
with citation requirements, and attribution verification.
"""

from snapagent.rag.chunking import semantic_chunk
from snapagent.rag.pipeline import RagPipeline
from snapagent.rag.reranker import Reranker
from snapagent.rag.schema import Citation, VerifiedAnswer
from snapagent.rag.validation import verify_citations

__all__ = [
    "Citation",
    "RagPipeline",
    "Reranker",
    "VerifiedAnswer",
    "semantic_chunk",
    "verify_citations",
]
