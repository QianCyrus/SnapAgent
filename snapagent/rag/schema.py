"""Pydantic models for structured RAG output with built-in validation.

Enforces citation requirements at the schema level so that substantive
answers always carry traceable source references.
"""

from __future__ import annotations

from pydantic import BaseModel, field_validator, model_validator


class Citation(BaseModel):
    """A single citation linking a claim to source material."""

    source_chunk: str
    exact_quote: str
    relevance: str

    @field_validator("exact_quote")
    @classmethod
    def quote_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("exact_quote must not be empty; copy verbatim text from the source.")
        return v.strip()


class VerifiedAnswer(BaseModel):
    """Structured answer with mandatory chain-of-thought and citations."""

    chain_of_thought: str
    citations: list[Citation] = []
    final_answer: str
    confidence: float = 0.0

    _REFUSAL_PHRASES: tuple[str, ...] = (
        "insufficient information",
        "not enough information",
        "cannot determine",
        "no relevant information",
        "unable to answer",
    )

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @model_validator(mode="after")
    def require_citations_for_claims(self) -> VerifiedAnswer:
        """Substantive answers must include at least one citation."""
        is_refusal = any(p in self.final_answer.lower() for p in self._REFUSAL_PHRASES)
        if not is_refusal and self.final_answer.strip() and not self.citations:
            raise ValueError(
                "Citations are REQUIRED for substantive answers. "
                "Provide exact verbatim quotes from the source material, "
                "or state that information is insufficient."
            )
        return self
