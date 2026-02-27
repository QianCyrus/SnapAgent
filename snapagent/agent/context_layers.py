"""Pluggable prompt-layer system for hierarchical system prompt assembly."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from snapagent.agent.memory import MemoryStore
    from snapagent.agent.skills import SkillsLoader


# ---------------------------------------------------------------------------
# Protocol + Registry
# ---------------------------------------------------------------------------


@runtime_checkable
class PromptLayer(Protocol):
    """Protocol for a single layer that contributes content to the system prompt."""

    @property
    def name(self) -> str: ...

    @property
    def priority(self) -> int: ...

    def render(self) -> str | None: ...


@dataclass
class LayerEntry:
    """Internal storage for a registered layer."""

    layer: PromptLayer
    enabled: bool = True


class LayerRegistry:
    """Ordered collection of PromptLayers that renders to a system prompt."""

    SEPARATOR = "\n\n---\n\n"

    def __init__(self) -> None:
        self._layers: dict[str, LayerEntry] = {}

    def register(self, layer: PromptLayer) -> None:
        """Register a layer. Replaces any existing layer with the same name."""
        self._layers[layer.name] = LayerEntry(layer=layer)

    def unregister(self, name: str) -> None:
        self._layers.pop(name, None)

    def enable(self, name: str, *, enabled: bool = True) -> None:
        if entry := self._layers.get(name):
            entry.enabled = enabled

    def render_all(self) -> str:
        """Render all enabled layers in priority order, joined by separator."""
        entries = sorted(
            (e for e in self._layers.values() if e.enabled),
            key=lambda e: e.layer.priority,
        )
        parts: list[str] = []
        for entry in entries:
            content = entry.layer.render()
            if content:
                parts.append(content)
        return self.SEPARATOR.join(parts)


# ---------------------------------------------------------------------------
# Built-in layers (extracted from the original ContextBuilder logic)
# ---------------------------------------------------------------------------

_BOOTSTRAP_FILES = ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md")


class IdentityLayer:
    """Emits the core identity section."""

    name = "identity"
    priority = 100

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def render(self) -> str | None:
        workspace_path = str(self._workspace.expanduser().resolve())
        system = platform.system()
        runtime = (
            f"{'macOS' if system == 'Darwin' else system} "
            f"{platform.machine()}, Python {platform.python_version()}"
        )
        return f"""# snapagent \U0001f408

You are snapagent, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable)
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

## snapagent Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

## Web Research Strategy
- Follow: PLAN what to search \u2192 SEARCH with a precise query \u2192 FETCH top result pages \
with web_fetch \u2192 SYNTHESIZE the answer.
- Do NOT call web_search more than twice for one question. If two searches have not \
answered the question, use web_fetch on promising URLs from existing results instead.
- NEVER repeat or rephrase a previous search query. Each search must target \
genuinely new information. Rewording the same question wastes tool calls.
- After receiving search results, STOP and evaluate: do you already have enough \
information to answer? If yes, answer immediately without further searches.
- When in doubt, answer with the information you have rather than searching again. \
Partial information with a caveat is better than an endless search loop.
- Use web_fetch on the most relevant URL(s) to get full page content before answering.

Reply directly with text for conversations. Only use the 'message' tool to send to a \
specific chat channel."""


class BootstrapLayer:
    """Loads workspace bootstrap files (AGENTS.md, SOUL.md, etc.)."""

    name = "bootstrap"
    priority = 200

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def render(self) -> str | None:
        parts: list[str] = []
        for filename in _BOOTSTRAP_FILES:
            file_path = self._workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        return "\n\n".join(parts) if parts else None


class MemoryLayer:
    """Injects long-term memory context."""

    name = "memory"
    priority = 300

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store

    def render(self) -> str | None:
        ctx = self._memory.get_memory_context()
        return f"# Memory\n\n{ctx}" if ctx else None


class AlwaysSkillsLayer:
    """Injects always-on skills content."""

    name = "always_skills"
    priority = 400

    def __init__(self, skills_loader: SkillsLoader) -> None:
        self._skills = skills_loader

    def render(self) -> str | None:
        always_skills = self._skills.get_always_skills()
        if not always_skills:
            return None
        content = self._skills.load_skills_for_context(always_skills)
        return f"# Active Skills\n\n{content}" if content else None


class SkillsSummaryLayer:
    """Emits a summary of available skills."""

    name = "skills_summary"
    priority = 500

    def __init__(self, skills_loader: SkillsLoader) -> None:
        self._skills = skills_loader

    def render(self) -> str | None:
        summary = self._skills.build_skills_summary()
        if not summary:
            return None
        return (
            "# Skills\n\n"
            "The following skills extend your capabilities. "
            "To use a skill, read its SKILL.md file using the read_file tool.\n"
            "Skills with available=\"false\" need dependencies installed first "
            "- you can try installing them with apt/brew.\n\n"
            + summary
        )
