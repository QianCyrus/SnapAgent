"""RAG pipeline orchestrating chunking, reranking, generation, and verification.

Implements the 'Golden Triangle' defense against hallucination:
1. Cross-encoder reranking to filter noise.
2. Structured output with mandatory citations.
3. Attribution verification with Self-Refine retry loop.
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger
from pydantic import ValidationError

from snapagent.providers.base import LLMProvider, LLMResponse
from snapagent.rag.chunking import semantic_chunk
from snapagent.rag.reranker import Reranker
from snapagent.rag.safety import check_safety
from snapagent.rag.schema import VerifiedAnswer
from snapagent.rag.validation import build_refine_feedback, verify_citations

_SYSTEM_PROMPT = """\
You are a fact-extraction engine. Answer ONLY from the provided source material.

RULES:
1. Use ONLY the source material below. NEVER use internal knowledge.
2. For each claim, cite an exact verbatim quote from the source.
3. If sources lack sufficient information, set final_answer to \
"Insufficient information in provided sources" and leave citations empty.
4. Show step-by-step reasoning in chain_of_thought.
5. Set confidence (0.0-1.0) reflecting how well sources support the answer.

Respond with valid JSON matching this schema:
{schema}"""


class RagPipeline:
    """Orchestrates the full anti-hallucination RAG pipeline.

    Stages:
        1. Semantic chunking of source material.
        2. Cross-encoder reranking to surface relevant chunks.
        3. Structured LLM generation with citation requirements.
        4. Attribution verification with Self-Refine retry loop.
        5. Safety filtering of final output.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        max_retries: int = 3,
    ):
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._max_retries = max_retries
        self._reranker = Reranker()

    async def query(
        self,
        query: str,
        context: str,
        *,
        max_chunks: int = 5,
    ) -> str:
        """Run the full RAG pipeline and return a fact-checked answer.

        Args:
            query: The user's question.
            context: Raw source text to search through.
            max_chunks: Maximum chunks to retain after reranking.

        Returns:
            Formatted answer string with citations, or an error message.
        """
        chunks = semantic_chunk(context)
        if not chunks:
            return "No processable content in the provided context."

        ranked = self._reranker.rerank(query, chunks, top_k=max_chunks)
        relevant_context = "\n\n---\n\n".join(ranked)

        answer = await self._generate_and_verify(query, relevant_context)

        is_safe, reason = check_safety(answer.final_answer)
        if not is_safe:
            return f"Response blocked by safety filter: {reason}"

        return _format_output(answer)

    async def _generate_and_verify(self, query: str, context: str) -> VerifiedAnswer:
        """Generate a structured answer with iterative citation verification."""
        schema_json = json.dumps(VerifiedAnswer.model_json_schema(), indent=2)
        system = _SYSTEM_PROMPT.format(schema=schema_json)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"SOURCE MATERIAL:\n{context}\n\nQUESTION: {query}"},
        ]

        last_error = ""
        for attempt in range(self._max_retries):
            response = await self._call_llm(messages)
            answer = _parse_response(response)

            if answer is None:
                last_error = "Failed to parse structured response from LLM."
                messages.append({"role": "assistant", "content": response.content or ""})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your response was not valid JSON matching the required schema. "
                        "Please respond with ONLY valid JSON."
                    ),
                })
                continue

            is_valid, errors = verify_citations(answer, context)
            if is_valid:
                return answer

            feedback = build_refine_feedback(errors)
            messages.append({"role": "assistant", "content": response.content or ""})
            messages.append({"role": "user", "content": feedback})
            last_error = "; ".join(errors)
            logger.debug("Citation verification failed (attempt {}): {}", attempt + 1, last_error)

        return VerifiedAnswer(
            chain_of_thought=f"Verification failed after {self._max_retries} attempts: {last_error}",
            citations=[],
            final_answer="Insufficient information in provided sources.",
            confidence=0.0,
        )

    async def _call_llm(self, messages: list[dict[str, Any]]) -> LLMResponse:
        """Call the LLM provider."""
        return await self._provider.chat(
            messages=messages,
            tools=None,
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )


def _parse_response(response: LLMResponse) -> VerifiedAnswer | None:
    """Parse LLM response content into a VerifiedAnswer."""
    content = (response.content or "").strip()
    if not content:
        return None

    data = _extract_json(content)
    if data is None:
        return None

    try:
        return VerifiedAnswer.model_validate(data)
    except ValidationError as e:
        logger.debug("Pydantic validation failed: {}", e)
        return None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from text, handling code fences and repair."""
    text = text.strip()

    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    try:
        import json_repair

        data = json_repair.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _format_output(answer: VerifiedAnswer) -> str:
    """Format a verified answer for display."""
    parts = [answer.final_answer]
    if answer.citations:
        parts.append("\n\n**Sources:**")
        for i, cite in enumerate(answer.citations, 1):
            parts.append(f'{i}. "{cite.exact_quote}"')
            if cite.relevance:
                parts.append(f"   - {cite.relevance}")
    parts.append(f"\n[Confidence: {answer.confidence:.0%}]")
    return "\n".join(parts)
