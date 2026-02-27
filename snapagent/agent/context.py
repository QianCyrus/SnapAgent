"""Context builder for assembling agent prompts."""

from __future__ import annotations

import base64
import mimetypes
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from snapagent.agent.context_layers import (
    AlwaysSkillsLayer,
    BootstrapLayer,
    IdentityLayer,
    LayerRegistry,
    MemoryLayer,
    SkillsSummaryLayer,
)
from snapagent.agent.memory import MemoryStore
from snapagent.agent.prompt_guard import BOUNDARY_PREAMBLE, ContentTagger, TrustLevel
from snapagent.agent.skills import SkillsLoader


class _SecurityPreambleLayer:
    """Injects content trust-boundary instructions at the very top of the prompt."""

    name = "security_preamble"
    priority = 50

    def render(self) -> str | None:
        return BOUNDARY_PREAMBLE


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]

    def __init__(self, workspace: Path, *, enable_content_tagging: bool = True):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
        self._enable_content_tagging = enable_content_tagging

        self._layers = LayerRegistry()
        if enable_content_tagging:
            self._layers.register(_SecurityPreambleLayer())
        self._layers.register(IdentityLayer(workspace))
        self._layers.register(BootstrapLayer(workspace))
        self._layers.register(MemoryLayer(self.memory))
        self._layers.register(AlwaysSkillsLayer(self.skills))
        self._layers.register(SkillsSummaryLayer(self.skills))

    @property
    def layers(self) -> LayerRegistry:
        """Expose layer registry for external registration of custom layers."""
        return self._layers

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """Build the system prompt from registered layers."""
        return self._layers.render_all()

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        raw = "\n".join(lines)
        return ContentTagger.wrap(raw, level=TrustLevel.UNTRUSTED, label="runtime_metadata")

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": self._build_runtime_context(channel, chat_id)},
            {"role": "user", "content": self._build_user_content(current_message, media)},
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(p.read_bytes()).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result}
        )
        return messages

    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        messages.append(msg)
        return messages
