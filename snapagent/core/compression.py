"""Context compression strategies for reducing model input cost."""

from __future__ import annotations

import re
from typing import Any

from snapagent.core.types import CompressedContext


class ContextCompressor:
    """Three-stage compression: recency keep + salient facts + rolling summary."""

    _KEYWORDS = (
        "must",
        "should",
        "require",
        "constraint",
        "deadline",
        "important",
        "remember",
        "error",
        "failed",
        "decision",
        "agreed",
        "todo",
        "api",
        "token",
        "password",
    )

    def __init__(
        self,
        *,
        enabled: bool = True,
        mode: str = "balanced",
        token_budget_ratio: float = 0.65,
        recency_turns: int = 6,
        salience_threshold: float = 0.7,
        max_facts: int = 12,
        max_summary_chars: int = 1400,
    ):
        self.enabled = enabled
        self.mode = mode
        self.token_budget_ratio = token_budget_ratio
        self.recency_turns = max(1, recency_turns)
        self.salience_threshold = salience_threshold
        self.max_facts = max(1, max_facts)
        self.max_summary_chars = max(200, max_summary_chars)

    @classmethod
    def from_config(cls, config: Any) -> "ContextCompressor":
        """Build compressor from Config.compression while staying loosely coupled."""
        return cls(
            enabled=getattr(config, "enabled", True),
            mode=getattr(config, "mode", "balanced"),
            token_budget_ratio=getattr(config, "token_budget_ratio", 0.65),
            recency_turns=getattr(config, "recency_turns", 6),
            salience_threshold=getattr(config, "salience_threshold", 0.7),
            max_facts=getattr(config, "max_facts", 12),
            max_summary_chars=getattr(config, "max_summary_chars", 1400),
        )

    def compress(self, history: list[dict[str, Any]]) -> CompressedContext:
        """Compress history into recent raw messages + compact metadata context."""
        if not history:
            return CompressedContext(
                raw_recent=[], token_budget_report={"mode": self.mode, "saved": 0}
            )
        if not self.enabled or self.mode == "off":
            return CompressedContext(
                raw_recent=list(history),
                token_budget_report={"mode": "off", "saved": 0, "input_messages": len(history)},
            )

        recent = self._slice_recent_by_turns(history)
        older = history[: len(history) - len(recent)]
        facts = self._extract_salient_facts(older)
        summary = self._build_rolling_summary(older)
        report = self._build_report(history, recent, facts, summary)
        return CompressedContext(
            raw_recent=recent, facts=facts, summary=summary, token_budget_report=report
        )

    def render_context_hint(self, compressed: CompressedContext) -> str:
        """Render compressed context into one metadata-only hint message."""
        if not compressed.has_payload:
            return ""

        lines = ["[Compressed Session Context - metadata only, not instructions]"]
        if compressed.facts:
            lines.append("Key facts and constraints:")
            lines.extend(f"- {fact}" for fact in compressed.facts)
        if compressed.summary:
            lines.append("Rolling summary:")
            lines.append(compressed.summary)
        return "\n".join(lines).strip()

    def _slice_recent_by_turns(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        user_seen = 0
        start = 0
        for idx in range(len(history) - 1, -1, -1):
            if history[idx].get("role") == "user":
                user_seen += 1
                if user_seen >= self.recency_turns:
                    start = idx
                    break
        return list(history[start:])

    def _extract_salient_facts(self, messages: list[dict[str, Any]]) -> list[str]:
        scored: list[tuple[float, str]] = []
        for msg in messages:
            text = self._extract_text(msg)
            if not text:
                continue
            score = self._score_message(msg.get("role", ""), text)
            if score < self.salience_threshold:
                continue
            snippet = self._normalize_snippet(text)
            if snippet:
                scored.append((score, snippet))

        if self.mode == "aggressive":
            cap = min(16, self.max_facts)
        elif self.mode == "balanced":
            cap = min(12, self.max_facts)
        else:
            cap = min(8, self.max_facts)

        scored.sort(key=lambda x: x[0], reverse=True)
        deduped: list[str] = []
        seen: set[str] = set()
        for _, fact in scored:
            norm = fact.lower()
            if norm in seen:
                continue
            deduped.append(fact)
            seen.add(norm)
            if len(deduped) >= cap:
                break
        return deduped

    def _build_rolling_summary(self, messages: list[dict[str, Any]]) -> str:
        if not messages:
            return ""

        picked: list[str] = []
        for msg in messages[-12:]:
            text = self._extract_text(msg)
            if not text:
                continue
            role = msg.get("role", "unknown")
            summary_line = self._normalize_snippet(text)
            if not summary_line:
                continue
            picked.append(f"{role}: {summary_line}")
            if len("\n".join(picked)) >= self.max_summary_chars:
                break

        return "\n".join(picked)[: self.max_summary_chars].strip()

    def _build_report(
        self,
        original: list[dict[str, Any]],
        recent: list[dict[str, Any]],
        facts: list[str],
        summary: str,
    ) -> dict[str, Any]:
        original_chars = sum(len(self._extract_text(msg)) for msg in original)
        kept_chars = sum(len(self._extract_text(msg)) for msg in recent)
        hint_chars = sum(len(item) for item in facts) + len(summary)
        before_tokens = max(1, original_chars // 4)
        after_tokens = max(1, (kept_chars + hint_chars) // 4)
        saved = max(0, before_tokens - after_tokens)
        return {
            "mode": self.mode,
            "token_budget_ratio": self.token_budget_ratio,
            "before_tokens_estimate": before_tokens,
            "after_tokens_estimate": after_tokens,
            "saved": saved,
            "recent_messages": len(recent),
            "facts": len(facts),
        }

    @staticmethod
    def _extract_text(msg: dict[str, Any]) -> str:
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") in ("text", "input_text", "output_text"):
                        text = item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                    elif item.get("type") == "image_url":
                        parts.append("[image]")
            return " ".join(parts)
        return ""

    @classmethod
    def _score_message(cls, role: str, text: str) -> float:
        score = 0.15
        if role == "user":
            score += 0.2
        elif role == "assistant":
            score += 0.1

        lowered = text.lower()
        score += min(0.4, 0.08 * sum(1 for kw in cls._KEYWORDS if kw in lowered))

        if re.search(r"\d", text):
            score += 0.1
        if "`" in text or "```" in text:
            score += 0.1
        if len(text) > 220:
            score += 0.1
        return min(1.0, score)

    @staticmethod
    def _normalize_snippet(text: str) -> str:
        one_line = " ".join(text.strip().split())
        if len(one_line) <= 220:
            return one_line
        return one_line[:217].rstrip() + "..."
