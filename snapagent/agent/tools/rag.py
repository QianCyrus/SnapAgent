"""RAG query tool for fact-checked document analysis."""

from __future__ import annotations

from typing import Any

from snapagent.agent.tools.base import Tool
from snapagent.providers.base import LLMProvider
from snapagent.rag.pipeline import RagPipeline


class RagQueryTool(Tool):
    """Answer a question using ONLY provided source text with citation verification."""

    name = "rag_query"
    description = (
        "Answer a question using ONLY the provided source text. "
        "Returns a fact-checked answer with verbatim citations. "
        "Use when accuracy matters and claims must be verified against source material."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question to answer based on the source text.",
            },
            "context": {
                "type": "string",
                "description": "The source text to search through for answers.",
            },
            "max_chunks": {
                "type": "integer",
                "description": "Maximum relevant chunks to consider (1-20).",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query", "context"],
    }

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ):
        self._pipeline = RagPipeline(
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def execute(
        self,
        query: str,
        context: str,
        max_chunks: int = 5,
        **kwargs: Any,
    ) -> str:
        if "maxChunks" in kwargs:
            max_chunks = kwargs["maxChunks"]
        return await self._pipeline.query(query, context, max_chunks=max_chunks)
