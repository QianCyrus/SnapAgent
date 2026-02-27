"""Integration test: orchestrator dedup prevents duplicate tool execution."""

from __future__ import annotations

from typing import Any

import pytest

from snapagent.adapters.tools import ToolGateway
from snapagent.agent.tools.base import Tool
from snapagent.agent.tools.registry import ToolRegistry
from snapagent.orchestrator.conversation import ConversationOrchestrator
from snapagent.providers.base import LLMResponse, ToolCallRequest


class _CountingSearchTool(Tool):
    """Tool that counts how many times execute() is called."""

    name = "web_search"
    description = "test search"
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def __init__(self):
        self.call_count = 0

    async def execute(self, **kwargs: Any) -> str:
        self.call_count += 1
        return f"Results for: {kwargs.get('query', '')}"


class _FakeProvider:
    """Provider returning pre-scripted responses."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._idx = 0

    async def chat(self, messages: list, tools: list | None = None) -> LLMResponse:
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


@pytest.mark.asyncio
async def test_duplicate_tool_call_executes_only_once():
    """Two identical web_search calls in one response should execute only once."""
    tool = _CountingSearchTool()
    registry = ToolRegistry()
    registry.register(tool)
    gateway = ToolGateway(registry)

    provider = _FakeProvider([
        LLMResponse(
            content="Searching...",
            tool_calls=[
                ToolCallRequest(id="tc1", name="web_search", arguments={"query": "Python"}),
                ToolCallRequest(id="tc2", name="web_search", arguments={"query": "Python"}),
            ],
        ),
        LLMResponse(content="Here is the answer.", tool_calls=[]),
    ])

    orch = ConversationOrchestrator(provider=provider, tools=gateway)
    result = await orch.run_agent_loop([{"role": "user", "content": "test"}])

    assert tool.call_count == 1
    assert "Here is the answer." in result.final_text


@pytest.mark.asyncio
async def test_different_queries_both_execute():
    """Different queries should both execute normally."""
    tool = _CountingSearchTool()
    registry = ToolRegistry()
    registry.register(tool)
    gateway = ToolGateway(registry)

    provider = _FakeProvider([
        LLMResponse(
            content="Searching...",
            tool_calls=[
                ToolCallRequest(id="tc1", name="web_search", arguments={"query": "Python"}),
                ToolCallRequest(id="tc2", name="web_search", arguments={"query": "Java"}),
            ],
        ),
        LLMResponse(content="Done.", tool_calls=[]),
    ])

    orch = ConversationOrchestrator(provider=provider, tools=gateway)
    await orch.run_agent_loop([{"role": "user", "content": "test"}])

    assert tool.call_count == 2


@pytest.mark.asyncio
async def test_search_loop_injects_nudge():
    """After 2 consecutive web_search iterations, a nudge message is injected."""
    tool = _CountingSearchTool()
    registry = ToolRegistry()
    registry.register(tool)
    gateway = ToolGateway(registry)

    provider = _FakeProvider([
        LLMResponse(
            content="s1",
            tool_calls=[
                ToolCallRequest(id="t1", name="web_search", arguments={"query": "q1"}),
            ],
        ),
        LLMResponse(
            content="s2",
            tool_calls=[
                ToolCallRequest(id="t2", name="web_search", arguments={"query": "q2"}),
            ],
        ),
        LLMResponse(content="Final answer.", tool_calls=[]),
    ])

    orch = ConversationOrchestrator(provider=provider, tools=gateway)
    result = await orch.run_agent_loop([{"role": "user", "content": "test"}])

    # Nudge should have been injected into messages after 2 consecutive searches
    nudge_messages = [
        m for m in result.messages
        if m.get("role") == "user" and "STOP SEARCHING" in m.get("content", "")
    ]
    assert len(nudge_messages) >= 1
    assert "Final answer." in result.final_text
