"""Unit tests for per-turn tool call deduplication and loop detection."""

from __future__ import annotations

from snapagent.orchestrator.dedup import ToolCallDedup


class TestToolCallDedup:
    def test_first_call_is_not_duplicate(self):
        dedup = ToolCallDedup()
        result = dedup.check("web_search", {"query": "Python"})
        assert result.is_duplicate is False
        assert result.cached_result is None

    def test_stored_call_is_duplicate(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python"}, "Results for: Python")
        result = dedup.check("web_search", {"query": "Python"})
        assert result.is_duplicate is True
        assert result.cached_result == "Results for: Python"

    def test_different_args_are_not_duplicate(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python"}, "result1")
        result = dedup.check("web_search", {"query": "Java"})
        assert result.is_duplicate is False

    def test_different_tool_names_are_not_duplicate(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python"}, "result1")
        result = dedup.check("web_fetch", {"query": "Python"})
        assert result.is_duplicate is False

    def test_arg_order_independent(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "test", "count": 5}, "result")
        result = dedup.check("web_search", {"count": 5, "query": "test"})
        assert result.is_duplicate is True

    def test_consecutive_search_below_threshold(self):
        dedup = ToolCallDedup(max_consecutive_searches=3)
        dedup.record_tool_name("web_search")
        dedup.record_tool_name("web_search")
        assert dedup.search_loop_detected is False

    def test_consecutive_search_at_threshold(self):
        dedup = ToolCallDedup(max_consecutive_searches=3)
        for _ in range(3):
            dedup.record_tool_name("web_search")
        assert dedup.search_loop_detected is True

    def test_non_search_tool_resets_counter(self):
        dedup = ToolCallDedup(max_consecutive_searches=3)
        dedup.record_tool_name("web_search")
        dedup.record_tool_name("web_search")
        dedup.record_tool_name("web_fetch")
        dedup.record_tool_name("web_search")
        assert dedup.search_loop_detected is False
        assert dedup.consecutive_search_count == 1

    def test_multiple_stores_same_key_overwrites(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "x"}, "old")
        dedup.store("web_search", {"query": "x"}, "new")
        result = dedup.check("web_search", {"query": "x"})
        assert result.cached_result == "new"
