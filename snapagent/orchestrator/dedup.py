"""Per-turn tool-call deduplication and search loop detection."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(slots=True)
class DeduplicatedResult:
    """Result of checking a tool call against the dedup cache."""

    is_duplicate: bool
    cached_result: str | None = None


class ToolCallDedup:
    """Per-turn cache that prevents identical tool calls and detects search loops.

    Created at the start of each ``run_agent_loop`` invocation and discarded
    when the method returns, so cached results never go stale across turns.
    """

    def __init__(self, *, max_consecutive_searches: int = 3):
        self._cache: dict[str, str] = {}
        self._consecutive_search_count: int = 0
        self._max_consecutive_searches = max_consecutive_searches

    @staticmethod
    def _make_key(name: str, arguments: dict) -> str:
        """Canonical cache key from tool name + sorted arguments."""
        return f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"

    def check(self, name: str, arguments: dict) -> DeduplicatedResult:
        """Return cached result if this exact call was already made this turn."""
        key = self._make_key(name, arguments)
        if key in self._cache:
            return DeduplicatedResult(is_duplicate=True, cached_result=self._cache[key])
        return DeduplicatedResult(is_duplicate=False)

    def store(self, name: str, arguments: dict, result: str) -> None:
        """Store a completed tool call result."""
        self._cache[self._make_key(name, arguments)] = result

    def record_tool_name(self, name: str) -> None:
        """Track consecutive web_search calls for loop detection."""
        if name == "web_search":
            self._consecutive_search_count += 1
        else:
            self._consecutive_search_count = 0

    @property
    def search_loop_detected(self) -> bool:
        """True when consecutive web_search calls hit the threshold."""
        return self._consecutive_search_count >= self._max_consecutive_searches

    @property
    def consecutive_search_count(self) -> int:
        return self._consecutive_search_count
