"""Tests for doctor_check observability tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from snapagent.config.schema import Config


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.mark.asyncio
async def test_doctor_tool_health_and_status(monkeypatch, tmp_path):
    from snapagent.agent.tools.doctor import DoctorCheckTool

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    data_dir = tmp_path / "data"

    monkeypatch.setattr("snapagent.agent.tools.doctor.load_config", lambda: config)
    monkeypatch.setattr("snapagent.agent.tools.doctor.get_config_path", lambda: config_path)
    monkeypatch.setattr("snapagent.agent.tools.doctor.get_data_dir", lambda: data_dir)

    tool = DoctorCheckTool()

    health_payload = json.loads(await tool.execute(check="health"))
    assert health_payload["check"] == "health"
    assert "snapshot" in health_payload
    assert "readiness" in health_payload["snapshot"]

    status_payload = json.loads(await tool.execute(check="status"))
    assert status_payload["check"] == "status"
    assert status_payload["config_path"] == str(config_path)
    assert status_payload["workspace"] == str(workspace)


@pytest.mark.asyncio
async def test_doctor_tool_logs_and_events(monkeypatch, tmp_path):
    from snapagent.agent.tools.doctor import DoctorCheckTool

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    data_dir = tmp_path / "data"
    log_path = data_dir / "logs" / "diagnostic.jsonl"

    rows = [
        {
            "ts": "2026-02-27T10:00:00Z",
            "name": "inbound.received",
            "component": "bus.queue",
            "severity": "info",
            "session_key": "telegram:1",
            "run_id": "run-a",
            "status": "ok",
            "attrs": {"content": "hello"},
        },
        {
            "ts": "2026-02-27T10:00:01Z",
            "name": "outbound.published",
            "component": "bus.queue",
            "severity": "info",
            "session_key": "telegram:1",
            "run_id": "run-a",
            "status": "ok",
            "attrs": {},
        },
        {
            "ts": "2026-02-27T10:00:02Z",
            "name": "inbound.received",
            "component": "bus.queue",
            "severity": "info",
            "session_key": "telegram:2",
            "run_id": "run-b",
            "status": "ok",
            "attrs": {"content": "ignore"},
        },
    ]
    _write_jsonl(log_path, rows)

    monkeypatch.setattr("snapagent.agent.tools.doctor.load_config", lambda: config)
    monkeypatch.setattr("snapagent.agent.tools.doctor.get_config_path", lambda: config_path)
    monkeypatch.setattr("snapagent.agent.tools.doctor.get_data_dir", lambda: data_dir)

    tool = DoctorCheckTool()

    logs_payload = json.loads(
        await tool.execute(check="logs", session_key="telegram:1", run_id="run-a", lines=10)
    )
    assert logs_payload["check"] == "logs"
    assert logs_payload["count"] == 2

    events_payload = json.loads(
        await tool.execute(check="events", session_key="telegram:1", run_id="run-a", lines=10)
    )
    assert events_payload["check"] == "events"
    assert events_payload["count"] == 2
    assert all("name" in item for item in events_payload["events"])
