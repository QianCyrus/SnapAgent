"""Shared core DTOs used across orchestrator and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
