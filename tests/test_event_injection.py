"""Tests for async event injection mechanism."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_messagebus_event_channel_creation() -> None:
    """Event channels should be created lazily and drained after reads."""
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    session_key = "telegram:12345"

    await bus.publish_event(session_key, "User sent: stop")

    assert session_key in bus._event_channels
    assert await bus.check_events(session_key) == "- User sent: stop"
    assert await bus.check_events(session_key) is None


@pytest.mark.asyncio
async def test_messagebus_event_accumulation() -> None:
    """Multiple queued events should be returned in one batch."""
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    session_key = "discord:67890"

    await bus.publish_event(session_key, "First")
    await bus.publish_event(session_key, "Second")
    await bus.publish_event(session_key, "Third")

    assert await bus.check_events(session_key) == "- First\n- Second\n- Third"
    assert await bus.check_events(session_key) is None


@pytest.mark.asyncio
async def test_messagebus_non_blocking_check() -> None:
    """check_events should return immediately when nothing is queued."""
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    start = asyncio.get_event_loop().time()
    event = await bus.check_events("test:key")
    elapsed = asyncio.get_event_loop().time() - start

    assert event is None
    assert elapsed < 0.01


def test_system_prompt_includes_event_handling(tmp_path) -> None:
    """Prompt should include interrupt instructions when enabled."""
    from snapagent.agent.context import ContextBuilder

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    builder = ContextBuilder(workspace)

    prompt = builder.build_system_prompt(enable_event_handling=True)

    assert "Event Handling" in prompt
    assert "<SYS_EVENT>" in prompt
    assert "IMMEDIATELY acknowledge" in prompt
    assert "ALWAYS takes priority" in prompt


def test_system_prompt_no_event_handling_by_default(tmp_path) -> None:
    """Prompt should remain unchanged unless explicitly enabled."""
    from snapagent.agent.context import ContextBuilder

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    builder = ContextBuilder(workspace)

    assert "Event Handling" not in builder.build_system_prompt()


@pytest.mark.asyncio
async def test_agent_loop_checks_events_before_llm() -> None:
    """Queued events should be injected before the next LLM call."""
    from snapagent.agent.loop import AgentLoop
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    response = MagicMock()
    response.has_tool_calls = False
    response.content = "Hello"
    response.reasoning_content = None
    response.usage = {}
    provider.chat = AsyncMock(return_value=response)

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("snapagent.agent.loop.ContextBuilder"),
        patch("snapagent.agent.loop.SessionManager"),
        patch("snapagent.agent.loop.SubagentManager"),
    ):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    await bus.publish_event("test:key", "User interrupt")
    _final_content, _tools_used, messages = await loop._run_agent_loop(
        initial_messages=[{"role": "user", "content": "test"}],
        session_key="test:key",
    )

    assert any(
        m.get("role") == "system"
        and "<SYS_EVENT" in m.get("content", "")
        and "User interrupt" in m.get("content", "")
        for m in messages
    )
    assert any(
        m.get("role") == "user" and "User interrupt" in str(m.get("content", ""))
        for m in messages
    )


@pytest.mark.asyncio
async def test_agent_loop_cancels_tools_on_event() -> None:
    """Pending tool calls should be cancelled if an interrupt arrives mid-turn."""
    from snapagent.agent.loop import AgentLoop
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"

    response = MagicMock()
    response.has_tool_calls = True
    response.content = "Let me search"
    response.reasoning_content = None
    response.usage = {}
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.name = "web_search"
    tool_call.arguments = {"query": "test"}
    response.tool_calls = [tool_call]

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("snapagent.agent.loop.ContextBuilder"),
        patch("snapagent.agent.loop.SessionManager"),
        patch("snapagent.agent.loop.SubagentManager"),
        patch("snapagent.agent.loop.ToolRegistry") as mock_registry_cls,
    ):
        registry = MagicMock()
        registry.get_definitions.return_value = []
        registry.execute = AsyncMock(return_value="result")
        mock_registry_cls.return_value = registry

        async def chat_with_event(*args, **kwargs):
            await bus.publish_event("test:key", "Stop now")
            return response

        provider.chat = AsyncMock(side_effect=chat_with_event)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)

    _final_content, tools_used, messages = await loop._run_agent_loop(
        initial_messages=[{"role": "user", "content": "test"}],
        session_key="test:key",
    )

    assert tools_used == []
    registry.execute.assert_not_called()
    assert any(
        m.get("role") == "tool" and "CANCELLED: User interrupted" in m.get("content", "")
        for m in messages
    )


def test_event_handling_config_default() -> None:
    """Feature should be opt-in by default."""
    from snapagent.config.schema import AgentDefaults

    assert AgentDefaults().enable_event_handling is False


def test_event_handling_config_enabled() -> None:
    """Feature should be configurable."""
    from snapagent.config.schema import AgentDefaults

    assert AgentDefaults(enable_event_handling=True).enable_event_handling is True


@pytest.mark.asyncio
async def test_event_published_when_active_task_exists() -> None:
    """An in-flight session marker should allow publishing interrupt events."""
    from snapagent.agent.loop import AgentLoop
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock()

    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("snapagent.agent.loop.ContextBuilder"),
        patch("snapagent.agent.loop.SessionManager"),
        patch("snapagent.agent.loop.SubagentManager"),
    ):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=workspace,
            enable_event_handling=True,
        )

    loop._processing_tasks.add("test:channel")

    if loop.enable_event_handling and "test:channel" in loop._processing_tasks:
        await bus.publish_event("test:channel", "Interrupt message")

    event = await bus.check_events("test:channel")
    assert event is not None
    assert "Interrupt message" in event


@pytest.mark.asyncio
async def test_pending_interrupt_event_is_replayed_as_follow_up() -> None:
    """Queued interrupt events should not be dropped after the active turn ends."""
    from pathlib import Path

    from snapagent.agent.loop import AgentLoop
    from snapagent.bus.events import InboundMessage, OutboundMessage
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock()

    with (
        patch("snapagent.agent.loop.ContextBuilder"),
        patch("snapagent.agent.loop.SessionManager"),
        patch("snapagent.agent.loop.SubagentManager"),
    ):
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=Path("/tmp"),
            enable_event_handling=True,
        )

    processed: list[str] = []

    async def fake_process(msg, *args, **kwargs):
        processed.append(msg.content)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="ok")

    loop._process_message = AsyncMock(side_effect=fake_process)  # type: ignore[method-assign]

    inbound = InboundMessage(
        channel="feishu",
        sender_id="u1",
        chat_id="c1",
        content="original task",
    )
    await bus.publish_event(inbound.session_key, "interrupt A")
    await bus.publish_event(inbound.session_key, "interrupt B")

    await loop._dispatch(inbound)
    await asyncio.sleep(0.05)

    assert processed[0] == "original task"
    assert len(processed) == 2
    assert "interrupt A" in processed[1]
    assert "interrupt B" in processed[1]
