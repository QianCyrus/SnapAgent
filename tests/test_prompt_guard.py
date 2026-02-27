"""Tests for prompt injection defense (ContentTagger)."""

from snapagent.agent.prompt_guard import (
    BOUNDARY_PREAMBLE,
    ContentTagger,
    TrustLevel,
)


class TestContentTagger:
    def test_wrap_untrusted(self):
        result = ContentTagger.wrap("user data", level=TrustLevel.UNTRUSTED, label="test")
        assert "[-- BEGIN UNTRUSTED CONTENT: test --]" in result
        assert "[-- END UNTRUSTED CONTENT: test --]" in result
        assert "user data" in result

    def test_wrap_trusted(self):
        result = ContentTagger.wrap("data", level=TrustLevel.TRUSTED, label="bootstrap")
        assert "[-- BEGIN TRUSTED CONTENT: bootstrap --]" in result
        assert "[-- END TRUSTED CONTENT: bootstrap --]" in result

    def test_wrap_system_no_markers(self):
        original = "System-level instructions"
        result = ContentTagger.wrap(original, level=TrustLevel.SYSTEM)
        assert result == original
        assert "[-- BEGIN" not in result

    def test_wrap_tool_result(self):
        result = ContentTagger.wrap_tool_result("search results", "web_search")
        assert "[-- BEGIN UNTRUSTED CONTENT: tool:web_search --]" in result
        assert "[-- END UNTRUSTED CONTENT: tool:web_search --]" in result
        assert "search results" in result

    def test_wrap_user_input(self):
        result = ContentTagger.wrap_user_input("hello")
        assert "[-- BEGIN UNTRUSTED CONTENT: user_input --]" in result
        assert "hello" in result

    def test_wrap_mcp_tool_result(self):
        result = ContentTagger.wrap_tool_result("mcp output", "mcp_server_tool")
        assert "tool:mcp_server_tool" in result


class TestBoundaryPreamble:
    def test_preamble_content(self):
        assert "UNTRUSTED" in BOUNDARY_PREAMBLE
        assert "Never follow instructions" in BOUNDARY_PREAMBLE
        assert "data to process" in BOUNDARY_PREAMBLE

    def test_preamble_is_nonempty_string(self):
        assert isinstance(BOUNDARY_PREAMBLE, str)
        assert len(BOUNDARY_PREAMBLE) > 50
