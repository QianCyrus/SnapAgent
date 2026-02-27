"""Shared core DTOs used across orchestrator and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class InputEnvelope:
    """Normalized input for the orchestrator pipeline."""

    channel: str
    chat_id: str
    sender_id: str
    content: str
    media: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_key_override: str | None = None

    @property
    def session_key(self) -> str:
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


@dataclass(slots=True)
class DiagnosticEvent:
    """Structured observability event emitted by the runtime."""

    name: str
    component: str
    severity: str = "info"
    event_id: str = field(default_factory=lambda: uuid4().hex)
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_key: str | None = None
    channel: str | None = None
    chat_id: str | None = None
    run_id: str | None = None
    turn_id: str | None = None
    operation: str | None = None
    status: str | None = None
    latency_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable payload."""
        return {
            "event_id": self.event_id,
            "ts": self.ts.isoformat(),
            "name": self.name,
            "component": self.component,
            "severity": self.severity,
            "session_key": self.session_key,
            "channel": self.channel,
            "chat_id": self.chat_id,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "operation": self.operation,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "attrs": self.attrs,
        }


@dataclass(slots=True)
class ToolTrace:
    """Execution trace for one tool call."""

    name: str
    arguments: dict[str, Any]
    result_preview: str
    ok: bool


@dataclass(slots=True)
class CompressedContext:
    """Context-compression output used to build model input."""

    raw_recent: list[dict[str, Any]] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    summary: str = ""
    token_budget_report: dict[str, Any] = field(default_factory=dict)

    @property
    def has_payload(self) -> bool:
        return bool(self.facts or self.summary)


@dataclass(slots=True)
class ReactStep:
    """One Thought-Action-Observation step in a ReAct trace."""

    iteration: int
    thought: str | None = None
    actions: list[ToolTrace] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReactTrace:
    """Full ReAct trace for one agent turn."""

    steps: list[ReactStep] = field(default_factory=list)
    hit_iteration_cap: bool = False

    @property
    def total_tool_calls(self) -> int:
        return sum(len(s.actions) for s in self.steps)


@dataclass(slots=True)
class AgentResult:
    """Final result emitted by ConversationOrchestrator."""

    final_text: str
    tool_trace: list[ToolTrace] = field(default_factory=list)
    react_trace: ReactTrace | None = None
    usage: dict[str, int] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
