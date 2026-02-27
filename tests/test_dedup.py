"""Unit tests for per-turn tool call deduplication and loop detection."""

from __future__ import annotations

from snapagent.orchestrator.dedup import ToolCallDedup, _normalize_query


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


class TestFuzzyQueryDedup:
    """Tests for near-duplicate search query detection."""

    def test_rephrased_query_is_duplicate(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "What is Python programming"}, "result1")
        result = dedup.check("web_search", {"query": "Python programming what is"})
        assert result.is_duplicate is True
        assert result.cached_result == "result1"

    def test_stop_words_stripped(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Tell me about machine learning"}, "result")
        result = dedup.check("web_search", {"query": "What is machine learning"})
        assert result.is_duplicate is True

    def test_case_insensitive_fuzzy(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python Tutorial"}, "result")
        result = dedup.check("web_search", {"query": "python tutorial"})
        assert result.is_duplicate is True

    def test_punctuation_ignored(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "What is Python?"}, "result")
        result = dedup.check("web_search", {"query": "What is Python"})
        assert result.is_duplicate is True

    def test_genuinely_different_query_not_duplicate(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python tutorial"}, "result1")
        result = dedup.check("web_search", {"query": "Rust memory safety"})
        assert result.is_duplicate is False

    def test_fuzzy_dedup_only_for_web_search(self):
        """Non-search tools should NOT get fuzzy matching."""
        dedup = ToolCallDedup()
        dedup.store("read_file", {"path": "/tmp/test.txt"}, "file contents")
        result = dedup.check("read_file", {"path": "/tmp/test.txt"})
        # Exact match still works
        assert result.is_duplicate is True

    def test_chinese_query_fuzzy(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python 教程 入门"}, "result")
        result = dedup.check("web_search", {"query": "入门 Python 教程"})
        assert result.is_duplicate is True


class TestSearchCap:
    """Tests for total search count hard cap."""

    def test_below_cap(self):
        dedup = ToolCallDedup(max_total_searches=4)
        for i in range(3):
            dedup.store("web_search", {"query": f"query {i}"}, f"result {i}")
        assert dedup.search_cap_reached is False

    def test_at_cap(self):
        dedup = ToolCallDedup(max_total_searches=4)
        for i in range(4):
            dedup.store("web_search", {"query": f"query {i}"}, f"result {i}")
        assert dedup.search_cap_reached is True

    def test_total_search_count(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "a"}, "r1")
        dedup.store("web_search", {"query": "b"}, "r2")
        dedup.store("web_fetch", {"url": "http://x"}, "r3")  # not a search
        assert dedup.total_search_count == 2

    def test_search_history(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "first"}, "r1")
        dedup.store("web_search", {"query": "second"}, "r2")
        assert dedup.search_history == ["first", "second"]

    def test_search_history_summary(self):
        dedup = ToolCallDedup()
        dedup.store("web_search", {"query": "Python basics"}, "r1")
        summary = dedup.search_history_summary()
        assert "Python basics" in summary
        assert "1." in summary

    def test_empty_history_summary(self):
        dedup = ToolCallDedup()
        assert "No searches" in dedup.search_history_summary()

    def test_default_consecutive_threshold_is_two(self):
        dedup = ToolCallDedup()
        dedup.record_tool_name("web_search")
        assert dedup.search_loop_detected is False
        dedup.record_tool_name("web_search")
        assert dedup.search_loop_detected is True


class TestNormalizeQuery:
    """Tests for the query normalisation helper."""

    def test_basic_normalisation(self):
        assert _normalize_query("What is Python?") == "python"

    def test_word_order_independent(self):
        assert _normalize_query("machine learning tutorial") == _normalize_query(
            "tutorial machine learning"
        )

    def test_stop_words_removed(self):
        assert _normalize_query("what is the best way to learn") == "best learn way"

    def test_deduplicates_tokens(self):
        assert _normalize_query("python python python") == "python"

    def test_empty_query(self):
        assert _normalize_query("") == ""

    def test_only_stop_words(self):
        assert _normalize_query("what is the") == ""

    def test_unicode_normalisation(self):
        # Full-width "Python" should normalise to "python"
        assert _normalize_query("Ｐｙｔｈｏｎ") == "python"
