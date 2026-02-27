"""Per-turn tool-call deduplication and search loop detection.

Supports both exact-match dedup (all tools) and fuzzy query dedup
(web_search) to prevent repeated/rephrased searches.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass


@dataclass(slots=True)
class DeduplicatedResult:
    """Result of checking a tool call against the dedup cache."""

    is_duplicate: bool
    cached_result: str | None = None


# ---------------------------------------------------------------------------
# Query normalisation helpers
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

# Common stop words stripped during normalisation so that rephrased queries
# like "what is X" vs "tell me about X" collapse to the same key.
_STOP_WORDS: frozenset[str] = frozenset(
    "a an the is are was were be been being do does did "
    "have has had having will would shall should may might can could "
    "of in on at to for with by from as into through about between "
    "what how who where when which why that this these those "
    "i me my we our you your he she it they them their "
    "and or but not no nor so yet "
    "tell me please show find get let"
    .split()
)


def _normalize_query(query: str) -> str:
    """Reduce a search query to a canonical form for fuzzy matching.

    Steps:
      1. NFKC normalise (full-width → ASCII, etc.)
      2. Lowercase
      3. Strip all punctuation
      4. Remove stop words
      5. Sort remaining tokens alphabetically
      6. Deduplicate tokens

    This means "What is Python?" and "python what is" produce the same key.
    """
    text = unicodedata.normalize("NFKC", query)
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = _WHITESPACE_RE.split(text.strip())
    meaningful = [t for t in tokens if t and t not in _STOP_WORDS]
    # Sort + dedup so word order doesn't matter.
    return " ".join(sorted(set(meaningful)))


# ---------------------------------------------------------------------------
# Main deduplicator
# ---------------------------------------------------------------------------


class ToolCallDedup:
    """Per-turn cache that prevents identical tool calls and detects search loops.

    Created at the start of each ``run_agent_loop`` invocation and discarded
    when the method returns, so cached results never go stale across turns.

    Enhancements over exact-match only:
      - **Fuzzy query dedup**: ``web_search`` calls are also checked against a
        normalised query index.  Rephrased/reworded queries that reduce to the
        same token set are treated as duplicates.
      - **Total search cap**: after ``max_total_searches`` web_search calls the
        dedup signals that no more searches should be executed.
      - **Consecutive threshold**: lowered to 2 (matching prompt guidance).
    """

    def __init__(
        self,
        *,
        max_consecutive_searches: int = 2,
        max_total_searches: int = 4,
    ):
        # Exact-match cache: key → result
        self._cache: dict[str, str] = {}
        self._consecutive_search_count: int = 0
        self._max_consecutive_searches = max_consecutive_searches
        self._max_total_searches = max_total_searches

        # Fuzzy query index: normalised_query → (original_query, result)
        self._search_index: dict[str, tuple[str, str]] = {}
        # Ordered list of original search queries for history reporting.
        self._search_history: list[str] = []

    # ---- key helpers ----

    @staticmethod
    def _make_key(name: str, arguments: dict) -> str:
        """Canonical cache key from tool name + sorted arguments."""
        return f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"

    # ---- public API ----

    def check(self, name: str, arguments: dict) -> DeduplicatedResult:
        """Return cached result if this call (or a near-duplicate) was already made."""
        # 1. Exact-match check (works for all tools).
        key = self._make_key(name, arguments)
        if key in self._cache:
            return DeduplicatedResult(is_duplicate=True, cached_result=self._cache[key])

        # 2. Fuzzy query check for web_search.
        if name == "web_search":
            raw_query = arguments.get("query", "")
            norm = _normalize_query(raw_query)
            if norm and norm in self._search_index:
                _, cached = self._search_index[norm]
                return DeduplicatedResult(is_duplicate=True, cached_result=cached)

        return DeduplicatedResult(is_duplicate=False)

    def store(self, name: str, arguments: dict, result: str) -> None:
        """Store a completed tool call result."""
        self._cache[self._make_key(name, arguments)] = result

        # Also index under normalised query for fuzzy matching.
        if name == "web_search":
            raw_query = arguments.get("query", "")
            norm = _normalize_query(raw_query)
            if norm:
                self._search_index[norm] = (raw_query, result)
            self._search_history.append(raw_query)

    def record_tool_name(self, name: str) -> None:
        """Track consecutive web_search calls for loop detection."""
        if name == "web_search":
            self._consecutive_search_count += 1
        else:
            self._consecutive_search_count = 0

    # ---- status queries ----

    @property
    def search_loop_detected(self) -> bool:
        """True when consecutive web_search calls hit the threshold."""
        return self._consecutive_search_count >= self._max_consecutive_searches

    @property
    def search_cap_reached(self) -> bool:
        """True when total web_search calls exceed the hard cap."""
        return len(self._search_history) >= self._max_total_searches

    @property
    def consecutive_search_count(self) -> int:
        return self._consecutive_search_count

    @property
    def total_search_count(self) -> int:
        return len(self._search_history)

    @property
    def search_history(self) -> list[str]:
        """Ordered list of original search queries made so far."""
        return list(self._search_history)

    def search_history_summary(self) -> str:
        """Human-readable summary of searches performed this turn."""
        if not self._search_history:
            return "No searches performed yet."
        lines = [f"  {i}. \"{q}\"" for i, q in enumerate(self._search_history, 1)]
        return "Searches already performed:\n" + "\n".join(lines)
