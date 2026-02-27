"""Tests for /doctor command lifecycle in AgentLoop."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snapagent.bus.events import InboundMessage
from snapagent.session.manager import Session


def _make_loop():
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

    session = Session(key="test:c1")
    loop.sessions = MagicMock()
    loop.sessions.get_or_create.return_value = session
    loop.sessions.save = MagicMock()
    loop._dispatch = AsyncMock(return_value=None)
    return loop, bus, session


@pytest.mark.asyncio
async def test_doctor_start_cancels_session_tasks_and_enables_mode():
    loop, bus, session = _make_loop()
    cancelled = asyncio.Event()

    async def slow_task():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(slow_task())
    await asyncio.sleep(0)
    loop._active_tasks["test:c1"] = [task]

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor")
    await loop._handle_doctor(msg)

    assert cancelled.is_set()
    assert session.metadata.get("doctor_mode") is True
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "doctor mode" in out.content.lower()


@pytest.mark.asyncio
async def test_doctor_status_reports_idle():
    loop, bus, _session = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor status")
    await loop._handle_doctor(msg)
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "idle" in out.content.lower()


@pytest.mark.asyncio
async def test_doctor_cancel_disables_mode():
    loop, bus, session = _make_loop()
    session.metadata["doctor_mode"] = True

    task = asyncio.create_task(asyncio.sleep(60))
    await asyncio.sleep(0)
    loop._doctor_tasks["test:c1"] = task
    loop._active_tasks["test:c1"] = [task]

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor cancel")
    await loop._handle_doctor(msg)

    assert "doctor_mode" not in session.metadata
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "cancel" in out.content.lower()


@pytest.mark.asyncio
async def test_doctor_start_shows_setup_guidance_when_provider_not_ready():
    loop, bus, session = _make_loop()
    loop._doctor_setup_guidance = MagicMock(return_value="setup guide")

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor")
    await loop._handle_doctor(msg)

    assert "doctor_mode" not in session.metadata
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "precheck blocked" in out.content.lower()
    assert "setup guide" in out.content
    loop._dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_help_includes_doctor_commands():
    loop, _bus, _session = _make_loop()
    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/help")
    result = await loop._process_message(msg)
    assert result is not None
    assert "/doctor" in result.content


@pytest.mark.asyncio
async def test_run_does_not_route_doctor_typo_to_doctor_handler():
    loop, bus, _session = _make_loop()
    loop._handle_doctor = AsyncMock()
    loop._dispatch = AsyncMock(return_value=None)

    runner = asyncio.create_task(loop.run())
    try:
        await bus.publish_inbound(
            InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctorr")
        )
        await asyncio.sleep(0.05)
    finally:
        loop.stop()
        await asyncio.wait_for(runner, timeout=2.0)

    loop._handle_doctor.assert_not_awaited()
    assert loop._dispatch.await_count == 1
