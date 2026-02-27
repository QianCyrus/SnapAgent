"""Read-only doctor diagnostics tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from snapagent.agent.tools.base import Tool
from snapagent.config.loader import get_config_path, get_data_dir, load_config
from snapagent.observability.health import collect_health_snapshot
from snapagent.observability.logging_sink import JsonlLoggingSink


class DoctorCheckTool(Tool):
    """Expose built-in observability checks for Codex-driven diagnostics."""

    @property
    def name(self) -> str:
        return "doctor_check"

    @property
    def description(self) -> str:
        return (
            "Run read-only SnapAgent diagnostics. "
            "Supports health, status, logs, and events checks."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "check": {
                    "type": "string",
                    "enum": ["health", "status", "logs", "events"],
                    "description": "Which diagnostic check to run.",
                },
                "session_key": {
                    "type": "string",
                    "description": "Optional session filter, e.g. telegram:12345.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional run correlation filter.",
                },
                "lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Max rows for logs/events checks.",
                },
            },
            "required": ["check"],
        }

    async def execute(
        self,
        *,
        check: str,
        session_key: str | None = None,
        run_id: str | None = None,
        lines: int = 120,
    ) -> str:
        limit = max(1, min(lines, 500))
        if check == "health":
            return self._health_payload()
        if check == "status":
            return self._status_payload()
        if check == "logs":
            return self._logs_payload(session_key=session_key, run_id=run_id, limit=limit)
        if check == "events":
            return self._events_payload(session_key=session_key, run_id=run_id, limit=limit)
        return f"Error: unknown check '{check}'"

    def _health_payload(self) -> str:
        config_path = get_config_path()
        config = load_config()
        snapshot = collect_health_snapshot(config=config, config_path=config_path).to_dict(deep=True)
        payload = {
            "check": "health",
            "snapshot": snapshot,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _status_payload(self) -> str:
        config_path = get_config_path()
        config = load_config()
        snapshot = collect_health_snapshot(config=config, config_path=config_path).to_dict(deep=True)
        payload = {
            "check": "status",
            "config_path": str(config_path),
            "workspace": str(config.workspace_path),
            "snapshot": snapshot,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _logs_payload(self, *, session_key: str | None, run_id: str | None, limit: int) -> str:
        sink = JsonlLoggingSink(self._log_path())
        rows = sink.query(session_key=session_key, run_id=run_id, limit=limit)
        payload = {
            "check": "logs",
            "session_key": session_key,
            "run_id": run_id,
            "count": len(rows),
            "rows": rows,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _events_payload(self, *, session_key: str | None, run_id: str | None, limit: int) -> str:
        sink = JsonlLoggingSink(self._log_path())
        rows = sink.query(session_key=session_key, run_id=run_id, limit=limit)
        events = [
            {
                "ts": row.get("ts"),
                "name": row.get("name"),
                "component": row.get("component"),
                "severity": row.get("severity"),
                "status": row.get("status"),
                "session_key": row.get("session_key"),
                "run_id": row.get("run_id"),
                "turn_id": row.get("turn_id"),
                "operation": row.get("operation"),
                "latency_ms": row.get("latency_ms"),
                "error_code": row.get("error_code"),
                "error_message": row.get("error_message"),
                "attrs": row.get("attrs", {}),
            }
            for row in rows
        ]
        payload = {
            "check": "events",
            "session_key": session_key,
            "run_id": run_id,
            "count": len(events),
            "events": events,
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _log_path() -> Path:
        return get_data_dir() / "logs" / "diagnostic.jsonl"
