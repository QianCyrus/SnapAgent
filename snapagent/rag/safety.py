"""Security filtering for RAG pipeline outputs.

Detects potentially dangerous intent patterns in generated text to prevent
prompt injection from propagating into agent actions.
"""

from __future__ import annotations

import re

_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\b(rm\s+-rf|rmdir\s+/|del\s+/[fqs]|format\s+[a-z]:)", re.I),
        "destructive filesystem command",
    ),
    (
        re.compile(r"\b(drop\s+table|delete\s+from\s+\w|truncate\s+table)", re.I),
        "destructive database command",
    ),
    (
        re.compile(
            r"\b(ignore|disregard|forget|override)\s+(all\s+)?"
            r"(previous|prior|above|earlier|system)\s+(instructions?|prompts?|rules?)",
            re.I,
        ),
        "prompt injection attempt",
    ),
    (
        re.compile(
            r"\b(api[_\s]?key|secret[_\s]?key|password|token|credentials?)\b"
            r".*\b(send|post|upload|expose|print|log|output)\b",
            re.I,
        ),
        "credential exfiltration attempt",
    ),
    (
        re.compile(r"\b(exec|eval|subprocess|os\.system|__import__)\s*\(", re.I),
        "code execution attempt",
    ),
]


def check_safety(text: str) -> tuple[bool, str | None]:
    """Check generated text for dangerous intent patterns.

    Args:
        text: Text to scan.

    Returns:
        Tuple of (is_safe, reason_if_unsafe).
    """
    for pattern, description in _DANGEROUS_PATTERNS:
        if pattern.search(text):
            return False, f"Blocked: {description}"
    return True, None
