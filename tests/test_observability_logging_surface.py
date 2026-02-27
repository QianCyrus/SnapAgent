"""Tests for Track 2 logging surface."""

from __future__ import annotations

import asyncio
import json

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
