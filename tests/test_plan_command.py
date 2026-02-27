"""Tests for /plan and /normal mode toggle in AgentLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snapagent.bus.events import InboundMessage
from snapagent.session.manager import Session


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

    # Replace session manager with one that returns a real Session
    session = Session(key="test:c1")
    loop.sessions = MagicMock()
    loop.sessions.get_or_create.return_value = session
    loop.sessions.save = MagicMock()
    return loop, bus, session


@pytest.mark.asyncio
async def test_plan_toggles_mode_on():
    """/plan sets plan_mode in session metadata."""
    loop, bus, session = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/plan")
    result = await loop._process_message(msg)
    assert result is not None
    assert "Plan mode ON" in result.content
    assert session.metadata.get("plan_mode") is True
    loop.sessions.save.assert_called()


@pytest.mark.asyncio
async def test_normal_toggles_mode_off():
    """/normal removes plan_mode from session metadata."""
    loop, bus, session = _make_loop()
    session.metadata["plan_mode"] = True
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/normal")
    result = await loop._process_message(msg)
    assert result is not None
    assert "Normal mode" in result.content
    assert "plan_mode" not in session.metadata
    loop.sessions.save.assert_called()


@pytest.mark.asyncio
async def test_help_includes_plan_and_normal():
    """/help output includes both /plan and /normal."""
    loop, bus, session = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/help")
    result = await loop._process_message(msg)
    assert result is not None
    assert "/plan" in result.content
    assert "/normal" in result.content
