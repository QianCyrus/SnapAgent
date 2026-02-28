"""Tests for /doctor command lifecycle in AgentLoop."""

from __future__ import annotations

import asyncio
import json
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
    loop._doctor_setup_guidance = MagicMock(return_value=None)
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
async def test_doctor_start_prefers_codex_cli_when_available():
    loop, bus, session = _make_loop()
    loop._doctor_setup_guidance = MagicMock(return_value=None)
    loop._doctor_cli_available = MagicMock(return_value=True)

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor")
    await loop._handle_doctor(msg)
    await asyncio.sleep(0)

    assert session.metadata.get("doctor_mode") is True
    loop._dispatch.assert_awaited_once()
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "doctor mode" in out.content.lower()


@pytest.mark.asyncio
async def test_doctor_start_falls_back_when_codex_cli_unavailable():
    loop, _bus, session = _make_loop()
    loop._doctor_setup_guidance = MagicMock(return_value=None)
    loop._doctor_cli_available = MagicMock(return_value=False)
    loop._run_doctor_via_codex_cli = AsyncMock(return_value=None)

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor")
    await loop._handle_doctor(msg)
    await asyncio.sleep(0)

    assert session.metadata.get("doctor_mode") is True
    loop._run_doctor_via_codex_cli.assert_not_awaited()
    assert loop._dispatch.await_count == 1


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
    loop._doctor_cli_available = MagicMock(return_value=False)

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor")
    await loop._handle_doctor(msg)

    assert "doctor_mode" not in session.metadata
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "precheck blocked" in out.content.lower()
    assert "setup guide" in out.content
    loop._dispatch.assert_not_called()


@pytest.mark.asyncio
async def test_doctor_start_skips_setup_guidance_when_codex_cli_available():
    loop, _bus, session = _make_loop()
    loop._doctor_setup_guidance = MagicMock(return_value="setup guide")
    loop._doctor_cli_available = MagicMock(return_value=True)

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/doctor")
    await loop._handle_doctor(msg)
    await asyncio.sleep(0)

    assert session.metadata.get("doctor_mode") is True
    loop._doctor_setup_guidance.assert_not_called()
    loop._dispatch.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_read_codex_cli_output_parses_session_and_message():
    loop, _bus, _session = _make_loop()
    reader = asyncio.StreamReader()
    reader.feed_data(
        (
            json.dumps({"type": "thread.started", "thread_id": "th_123"}) + "\n"
            + json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "diag ok"}],
                    },
                }
            )
            + "\n"
        ).encode("utf-8")
    )
    reader.feed_eof()

    output, session_id = await loop._read_codex_cli_output(reader)
    assert output == "diag ok"
    assert session_id == "th_123"


def test_build_doctor_codex_command_with_resume_session():
    loop, _bus, _session = _make_loop()
    loop._doctor_codex_model = MagicMock(return_value="gpt-5.3-codex")

    cmd = loop._build_doctor_codex_command(
        "check status",
        resume_session_id="th_abc",
    )
    assert cmd[:4] == ["codex", "exec", "resume", "--json"]
    assert "th_abc" in cmd
    assert cmd[-1] == "check status"


@pytest.mark.asyncio
async def test_run_doctor_via_codex_cli_persists_session_id(monkeypatch):
    loop, bus, session = _make_loop()

    class _FakeProc:
        def __init__(self):
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(
                (
                    json.dumps({"type": "thread.started", "thread_id": "th_saved"}) + "\n"
                    + json.dumps(
                        {
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": "done"}],
                            },
                        }
                    )
                    + "\n"
                ).encode("utf-8")
            )
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode = None

        async def wait(self):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    async def _fake_spawn(*_args, **_kwargs):
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_spawn)

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="diag")
    await loop._run_doctor_via_codex_cli(
        msg=msg,
        prompt="diag",
        run_id="r1",
        turn_id="t1",
        session_key="test:c1",
    )

    assert session.metadata.get("doctor_codex_session_id") == "th_saved"
    out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
    assert "codex session: th_saved" in out.content


@pytest.mark.asyncio
async def test_process_message_doctor_mode_routes_to_codex_cli():
    loop, _bus, session = _make_loop()
    session.metadata["doctor_mode"] = True
    loop._doctor_cli_available = MagicMock(return_value=True)
    loop._run_doctor_via_codex_cli = AsyncMock(return_value=("diag ok", True))

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="check logs")
    result = await loop._process_message(msg)

    assert result is not None
    assert result.content == "diag ok"
    assert result.channel == "test"
    assert result.chat_id == "c1"
    loop._run_doctor_via_codex_cli.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_message_doctor_mode_falls_back_to_provider_when_codex_fails():
    loop, _bus, session = _make_loop()
    session.metadata["doctor_mode"] = True
    loop._doctor_cli_available = MagicMock(return_value=True)
    loop._run_doctor_via_codex_cli = AsyncMock(return_value=("codex failed", False))
    loop._run_agent_loop = AsyncMock(
        return_value=(
            "provider diag",
            [],
            [{"role": "assistant", "content": "provider diag"}],
        )
    )

    msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="check logs")
    result = await loop._process_message(msg)

    assert result is not None
    assert result.content == "provider diag"
    loop._run_doctor_via_codex_cli.assert_awaited_once()
    loop._run_agent_loop.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_direct_returns_doctor_cli_output_without_empty_fallback():
    loop, _bus, session = _make_loop()
    session.metadata["doctor_mode"] = True
    loop._doctor_cli_available = MagicMock(return_value=True)
    loop._run_doctor_via_codex_cli = AsyncMock(return_value=("diag via cli", True))
    loop._connect_mcp = AsyncMock(return_value=None)

    response = await loop.process_direct(
        "check logs",
        session_key="test:c1",
        channel="cli",
        chat_id="c1",
    )

    assert response == "diag via cli"
    loop._run_doctor_via_codex_cli.assert_awaited_once()
