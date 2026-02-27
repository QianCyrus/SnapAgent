"""Tests for ReAct trace types and orchestrator integration."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from snapagent.core.types import AgentResult, ReactStep, ReactTrace, ToolTrace


class TestReactStep:
    def test_default_fields(self):
        step = ReactStep(iteration=1)
        assert step.iteration == 1
        assert step.thought is None
        assert step.actions == []
        assert step.observations == []

    def test_with_actions(self):
        trace = ToolTrace(name="web_search", arguments={"q": "test"}, result_preview="ok", ok=True)
        step = ReactStep(iteration=2, thought="searching", actions=[trace], observations=["ok"])
        assert len(step.actions) == 1
        assert step.actions[0].name == "web_search"


class TestReactTrace:
    def test_empty_trace(self):
        trace = ReactTrace()
        assert trace.total_tool_calls == 0
        assert trace.hit_iteration_cap is False

    def test_total_tool_calls(self):
        t1 = ToolTrace(name="a", arguments={}, result_preview="", ok=True)
        t2 = ToolTrace(name="b", arguments={}, result_preview="", ok=True)
        steps = [
            ReactStep(iteration=1, actions=[t1, t2]),
            ReactStep(iteration=2, actions=[t1]),
        ]
        trace = ReactTrace(steps=steps)
        assert trace.total_tool_calls == 3

    def test_hit_iteration_cap(self):
        trace = ReactTrace(hit_iteration_cap=True)
        assert trace.hit_iteration_cap is True


class TestAgentResultReactTrace:
    def test_default_none(self):
        result = AgentResult(final_text="done")
        assert result.react_trace is None

    def test_with_react_trace(self):
        trace = ReactTrace(steps=[ReactStep(iteration=1, thought="done")])
        result = AgentResult(final_text="done", react_trace=trace)
        assert result.react_trace is not None
        assert len(result.react_trace.steps) == 1


class _FakeResponse:
    """Minimal fake LLM response for orchestrator tests."""

    def __init__(
        self,
        content: str | None = None,
        tool_calls: list | None = None,
        reasoning_content: str | None = None,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.has_tool_calls = bool(self.tool_calls)
        self.finish_reason = "stop"
        self.usage = {}
        self.reasoning_content = reasoning_content


@dataclass
class _FakeToolCall:
    id: str = "tc_1"
    name: str = "web_search"
    arguments: dict = field(default_factory=lambda: {"query": "test"})


class _FakeProvider:
    """Provider that returns a sequence of responses."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self._idx = 0

    async def chat(self, messages, tools=None):
        resp = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return resp


class _FakeToolGateway:
    """Tool gateway that returns a fixed result."""

    def definitions(self):
        return []

    async def invoke(self, name, arguments):
        return "result_ok", ToolTrace(
            name=name, arguments=arguments, result_preview="result_ok", ok=True
        )


@pytest.mark.asyncio
async def test_react_trace_single_tool_call():
    from snapagent.orchestrator.conversation import ConversationOrchestrator

    provider = _FakeProvider([
        _FakeResponse(content="thinking...", tool_calls=[_FakeToolCall()]),
        _FakeResponse(content="done"),
    ])
    orch = ConversationOrchestrator(provider=provider, tools=_FakeToolGateway(), max_iterations=40)
    result = await orch.run_agent_loop([{"role": "user", "content": "hi"}])

    assert result.react_trace is not None
    assert len(result.react_trace.steps) == 2
    # First step has tool call
    assert len(result.react_trace.steps[0].actions) == 1
    assert result.react_trace.steps[0].observations == ["result_ok"]
    # Second step is final answer
    assert result.react_trace.steps[1].actions == []
    assert result.react_trace.hit_iteration_cap is False


@pytest.mark.asyncio
async def test_react_trace_no_tools():
    from snapagent.orchestrator.conversation import ConversationOrchestrator

    provider = _FakeProvider([_FakeResponse(content="direct answer")])
    orch = ConversationOrchestrator(provider=provider, tools=_FakeToolGateway(), max_iterations=40)
    result = await orch.run_agent_loop([{"role": "user", "content": "hi"}])

    assert result.react_trace is not None
    assert len(result.react_trace.steps) == 1
    assert result.react_trace.steps[0].thought == "direct answer"
    assert result.react_trace.steps[0].actions == []


@pytest.mark.asyncio
async def test_react_trace_iteration_cap():
    from snapagent.orchestrator.conversation import ConversationOrchestrator

    # Provider always returns tool calls — will hit cap.
    provider = _FakeProvider([
        _FakeResponse(content="thinking", tool_calls=[_FakeToolCall()])
    ])
    orch = ConversationOrchestrator(provider=provider, tools=_FakeToolGateway(), max_iterations=3)
    result = await orch.run_agent_loop([{"role": "user", "content": "hi"}])

    assert result.react_trace is not None
    assert result.react_trace.hit_iteration_cap is True
    assert len(result.react_trace.steps) == 3
    assert result.diagnostics["react_steps"] == 3
