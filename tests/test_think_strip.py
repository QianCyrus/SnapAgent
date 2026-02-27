"""Tests for ThinkTagStripper."""

from snapagent.utils.think_strip import ThinkTagStripper


class TestThinkTagStripper:
    stripper = ThinkTagStripper()

    def test_strip_basic_think_tags(self):
        text = "Hello <think>internal reasoning</think> world"
        assert self.stripper.strip(text) == "Hello  world"

    def test_strip_multiline_think(self):
        text = "<think>\nstep 1\nstep 2\n</think>Final answer."
        assert self.stripper.strip(text) == "Final answer."

    def test_strip_nested_think_tags(self):
        text = "<think>outer <think>inner</think> still outer</think>result"
        assert self.stripper.strip(text) == "result"

    def test_strip_unclosed_trailing_tag(self):
        text = "Answer <think>reasoning that never closes..."
        assert self.stripper.strip(text) == "Answer"

    def test_strip_alternative_reasoning_tag(self):
        text = "Hello <reasoning>internal logic</reasoning> world"
        assert self.stripper.strip(text) == "Hello  world"

    def test_strip_alternative_thought_tag(self):
        text = "<thought>internal</thought>result"
        assert self.stripper.strip(text) == "result"

    def test_strip_alternative_inner_monologue_tag(self):
        text = "prefix<inner_monologue>thoughts</inner_monologue>suffix"
        assert self.stripper.strip(text) == "prefixsuffix"

    def test_strip_mixed_tags(self):
        text = "<think>a</think>middle<reasoning>b</reasoning>end"
        assert self.stripper.strip(text) == "middleend"

    def test_strip_preserves_normal_content(self):
        text = "This is a perfectly normal response with no special tags."
        assert self.stripper.strip(text) == text

    def test_strip_returns_none_for_empty(self):
        assert self.stripper.strip("") is None
        assert self.stripper.strip(None) is None
        assert self.stripper.strip("<think>only reasoning</think>") is None

    def test_strip_case_insensitive(self):
        text = "<THINK>reasoning</THINK>result"
        assert self.stripper.strip(text) == "result"

    def test_strip_unclosed_with_preceding_content(self):
        text = "Answer is 42. <think>let me verify..."
        assert self.stripper.strip(text) == "Answer is 42."
