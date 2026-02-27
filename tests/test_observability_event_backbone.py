"""Tests for Track 0 observability event backbone foundation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snapagent.bus.events import InboundMessage, OutboundMessage
from snapagent.bus.queue import MessageBus
from snapagent.core.types import DiagnosticEvent


@pytest.mark.asyncio
async def test_message_bus_emits_diagnostic_events() -> None:
    captured: list[DiagnosticEvent] = []

    async def _emit(ev: DiagnosticEvent) -> None:
        captured.append(ev)

    bus = MessageBus(event_emitter=_emit)

    inbound = InboundMessage(
        channel="telegram",
        sender_id="u1",
        chat_id="c1",
        content="hello",
        run_id="run-1",
        turn_id="turn-1",
    )
    await bus.publish_inbound(inbound)

    outbound = OutboundMessage(
        channel="telegram",
        chat_id="c1",
        content="world",
        run_id="run-1",
        turn_id="turn-1",
    )
    await bus.publish_outbound(outbound)

    names = [e.name for e in captured]
    assert "inbound.received" in names
    assert "outbound.published" in names
    assert captured[0].run_id == "run-1"
    assert captured[0].turn_id == "turn-1"


def test_diagnostic_event_schema_fields() -> None:
    ev = DiagnosticEvent(name="turn.started", component="agent.loop", status="ok")

    payload = ev.to_dict()

    assert payload["name"] == "turn.started"
    assert payload["component"] == "agent.loop"
    assert payload["status"] == "ok"
    assert payload["event_id"]
    assert payload["ts"]


@pytest.mark.asyncio
async def test_message_bus_emitter_failure_isolated() -> None:
    async def _boom(_: DiagnosticEvent) -> None:
        raise RuntimeError("boom")

    bus = MessageBus(event_emitter=_boom)
    await bus.publish_inbound(
        InboundMessage(channel="cli", sender_id="u", chat_id="c", content="x")
    )

    got = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    assert got.content == "x"


def _make_loop():
    from snapagent.agent.loop import AgentLoop

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
    return loop


@pytest.mark.asyncio
async def test_agent_loop_assigns_and_propagates_correlation_ids() -> None:
    loop = _make_loop()

    session = MagicMock()
    session.key = "cli:direct"
    session.metadata = {}
    session.messages = []
    session.last_consolidated = 0
    session.get_history.return_value = []

    loop.sessions.get_or_create.return_value = session
    loop.sessions.save.return_value = None
    loop._build_initial_messages = MagicMock(return_value=([{"role": "user", "content": "hi"}], {}))
    loop._run_agent_loop = AsyncMock(return_value=("done", [], [{"role": "assistant", "content": "done"}]))

    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="hello")
    out = await loop._process_message(msg)

    assert out is not None
    assert out.run_id is not None
    assert out.turn_id is not None
