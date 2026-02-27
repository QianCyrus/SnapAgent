"""Redaction helpers for observability payloads."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "***REDACTED***"

_SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "sessionid",
    "private_key",
)

_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+\b")
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.lower().replace("-", "_")
    return any(token in normalized for token in _SENSITIVE_KEYWORDS)


def _mask_email(match: re.Match[str]) -> str:
    local = match.group(1)
    domain = match.group(2)
    head, _, suffix = domain.partition(".")

    local_masked = f"{local[:1]}***" if local else "***"
    head_masked = f"{head[:1]}***" if head else "***"
    return f"{local_masked}@{head_masked}.{suffix}" if suffix else f"{local_masked}@{head_masked}"


def _redact_text(text: str) -> str:
    redacted = _EMAIL_RE.sub(_mask_email, text)
    redacted = _BEARER_RE.sub(f"Bearer {REDACTED}", redacted)
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def _redact(value: Any, key: str | None = None) -> Any:
    if _is_sensitive_key(key):
        return REDACTED

    if isinstance(value, dict):
        return {k: _redact(v, str(k)) for k, v in value.items()}

    if isinstance(value, list):
        return [_redact(item, key) for item in value]

    if isinstance(value, tuple):
        return tuple(_redact(item, key) for item in value)

    if isinstance(value, str):
        return _redact_text(value)

    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted copy of the observability payload."""
    return _redact(payload)
