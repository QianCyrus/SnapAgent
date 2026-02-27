"""Tests for Track 2 logging surface."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time

from typer.testing import CliRunner

from snapagent.cli.commands import app
from snapagent.core.types import DiagnosticEvent
from snapagent.observability.logging_sink import JsonlLoggingSink
from snapagent.observability.redaction import REDACTED, redact_payload

runner = CliRunner()


def test_redaction_masks_sensitive_fields() -> None:
    payload = {
        "attrs": {
            "api_key": "sk-super-secret",
            "cookie": "sessionid=abc",
            "note": "Contact me at alice@example.com",
        }
    }

    redacted = redact_payload(payload)

    assert redacted["attrs"]["api_key"] == REDACTED
    assert redacted["attrs"]["cookie"] == REDACTED
    assert "alice@example.com" not in redacted["attrs"]["note"]


def test_jsonl_sink_is_append_only_and_queryable(tmp_path) -> None:
    sink = JsonlLoggingSink(tmp_path / "logs" / "diagnostic.jsonl")

    asyncio.run(
        sink.emit(
            DiagnosticEvent(
                name="inbound.received",
                component="bus.queue",
                session_key="cli:chat-a",
                run_id="run-a",
                attrs={"api_key": "sk-abc123"},
            )
        )
    )
    asyncio.run(
        sink.emit(
            DiagnosticEvent(
                name="outbound.published",
                component="bus.queue",
                session_key="cli:chat-b",
                run_id="run-b",
            )
        )
    )

    filtered = sink.query(session_key="cli:chat-a", run_id="run-a", limit=10)
    all_rows = sink.query(limit=10)

    assert len(filtered) == 1
    assert filtered[0]["session_key"] == "cli:chat-a"
    assert filtered[0]["run_id"] == "run-a"
    assert filtered[0]["attrs"]["api_key"] == REDACTED
    assert len(all_rows) == 2


def test_logs_command_supports_filters_and_json_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("snapagent.config.loader.get_data_dir", lambda: tmp_path)
    sink = JsonlLoggingSink(tmp_path / "logs" / "diagnostic.jsonl")

    asyncio.run(
        sink.emit(
            DiagnosticEvent(
                name="inbound.received",
                component="bus.queue",
                session_key="cli:chat-1",
                run_id="run-keep",
                attrs={"token": "tok-123"},
            )
        )
    )
    asyncio.run(
        sink.emit(
            DiagnosticEvent(
                name="inbound.received",
                component="bus.queue",
                session_key="cli:chat-2",
                run_id="run-drop",
            )
        )
    )

    result = runner.invoke(
        app,
        ["logs", "--session", "cli:chat-1", "--run", "run-keep", "--json", "--lines", "10"],
    )

    assert result.exit_code == 0
    rows = [line for line in result.stdout.splitlines() if line.startswith("{")]
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["session_key"] == "cli:chat-1"
    assert payload["run_id"] == "run-keep"
    assert payload["attrs"]["token"] == REDACTED


def test_logs_command_supports_follow_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("snapagent.config.loader.get_data_dir", lambda: tmp_path)

    def _fake_query(self, **kwargs):
        return []

    def _fake_follow(self, **kwargs):
        yield {
            "ts": "2026-02-27T00:00:00+00:00",
            "name": "outbound.published",
            "component": "bus.queue",
            "severity": "info",
            "session_key": "cli:chat-1",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "status": "ok",
            "attrs": {},
        }

    monkeypatch.setattr(JsonlLoggingSink, "query", _fake_query)
    monkeypatch.setattr(JsonlLoggingSink, "follow", _fake_follow)

    result = runner.invoke(app, ["logs", "--follow", "--json"])

    assert result.exit_code == 0
    assert '"name": "outbound.published"' in result.stdout


def test_follow_continues_after_rotation(tmp_path) -> None:
    sink = JsonlLoggingSink(
        tmp_path / "logs" / "diagnostic.jsonl",
        rotate_bytes=450,
        max_backups=1,
    )
    out: queue.Queue[dict] = queue.Queue()

    def _consume_two() -> None:
        gen = sink.follow(poll_interval=0.02)
        out.put(next(gen))
        out.put(next(gen))

    thread = threading.Thread(target=_consume_two, daemon=True)
    thread.start()
    time.sleep(0.1)

    asyncio.run(sink.emit(DiagnosticEvent(name="first", component="test")))

    first = out.get(timeout=1.0)
    assert first["name"] == "first"

    # Force rotation with larger payloads, then emit a marker event.
    for i in range(10):
        asyncio.run(
            sink.emit(
                DiagnosticEvent(
                    name=f"bulk-{i}",
                    component="test",
                    attrs={"blob": "x" * 120},
                )
            )
        )
    asyncio.run(sink.emit(DiagnosticEvent(name="after-rotate", component="test")))

    second = out.get(timeout=2.0)
    assert second["name"] == "after-rotate"


def test_agent_single_message_emits_observability_logs(tmp_path, monkeypatch) -> None:
    from snapagent.config.schema import Config
    from snapagent.providers.base import LLMProvider, LLMResponse

    monkeypatch.setattr("snapagent.config.loader.get_data_dir", lambda: tmp_path)

    config = Config()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config.agents.defaults.workspace = str(workspace)

    class _FakeProvider(LLMProvider):
        async def chat(
            self,
            messages,
            tools=None,
            model=None,
            max_tokens=4096,
            temperature=0.7,
        ):
            return LLMResponse(content="ok")

        def get_default_model(self) -> str:
            return "fake-model"

    monkeypatch.setattr("snapagent.config.loader.load_config", lambda: config)
    monkeypatch.setattr("snapagent.cli.commands._make_provider", lambda _config: _FakeProvider())

    result = runner.invoke(app, ["agent", "-m", "ping", "--no-markdown"])

    assert result.exit_code == 0

    sink = JsonlLoggingSink(tmp_path / "logs" / "diagnostic.jsonl")
    rows = sink.query(limit=20)
    names = [row.get("name") for row in rows]

    assert "inbound.received" in names
    assert "outbound.published" in names
