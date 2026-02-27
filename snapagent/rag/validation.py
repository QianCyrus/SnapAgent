"""Citation verification implementing ReClaim attribution logic.

Verifies that every citation's exact_quote exists verbatim in the source
material, catching fabricated references before they reach the user.
"""

from __future__ import annotations

import re

from snapagent.rag.schema import VerifiedAnswer


def verify_citations(answer: VerifiedAnswer, context: str) -> tuple[bool, list[str]]:
    """Verify all citations reference text that exists in the source context.

    Args:
        answer: Structured answer containing citations to verify.
        context: Original source material.

    Returns:
        Tuple of (all_valid, list_of_error_messages).
    """
    if not answer.citations:
        return True, []

    normalized_ctx = _normalize_ws(context.lower())
    errors: list[str] = []

    for i, cite in enumerate(answer.citations, 1):
        quote = cite.exact_quote.strip()
        if not quote:
            errors.append(f"Citation {i}: empty quote.")
            continue

        if _normalize_ws(quote.lower()) not in normalized_ctx:
            preview = quote[:80] + "..." if len(quote) > 80 else quote
            errors.append(
                f"Citation {i}: quote not found in source material. "
                f"'{preview}' does not appear in the provided context. "
                "Copy exact text from the source; do not paraphrase."
            )

    return len(errors) == 0, errors


def build_refine_feedback(errors: list[str]) -> str:
    """Build a Self-Refine feedback message from verification errors.

    Args:
        errors: Verification error messages.

    Returns:
        Formatted feedback string for the LLM retry prompt.
    """
    return (
        "CITATION VERIFICATION FAILED. Fix the following errors:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\nYou MUST provide exact verbatim quotes that exist in the source material. "
        "Do NOT fabricate, paraphrase, or rearrange words. "
        "Copy text directly from the source. "
        "If the information is not available, state "
        "'Insufficient information in provided sources'."
    )


def _normalize_ws(text: str) -> str:
    """Collapse all whitespace to single spaces for fuzzy matching."""
    return re.sub(r"\s+", " ", text).strip()
