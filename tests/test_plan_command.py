"""Tests for /plan command dispatch in AgentLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snapagent.bus.events import InboundMessage


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from snapagent.agent.loop import AgentLoop
    from snapagent.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("snapagent.agent.loop.ContextBuilder"),
        patch("snapagent.agent.loop.SessionManager"),
        patch("snapagent.agent.loop.SubagentManager") as mock_sub_mgr,
    ):
        mock_sub_mgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


@pytest.mark.asyncio
async def test_plan_empty_shows_usage():
    """'/plan' with no content returns usage hint."""
    loop, bus = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/plan")
    result = await loop._process_message(msg)
    assert result is not None
    assert "Usage: /plan" in result.content


@pytest.mark.asyncio
async def test_plan_spaces_only_shows_usage():
    """'/plan   ' (spaces only) returns usage hint."""
    loop, bus = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/plan   ")
    result = await loop._process_message(msg)
    assert result is not None
    assert "Usage: /plan" in result.content


@pytest.mark.asyncio
async def test_help_includes_plan():
    """'/help' output includes /plan command."""
    loop, bus = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/help")
    result = await loop._process_message(msg)
    assert result is not None
    assert "/plan" in result.content
