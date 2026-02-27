"""Tool adapter used by the orchestrator."""

from __future__ import annotations

from typing import Any

from snapagent.agent.tools.registry import ToolRegistry
from snapagent.core.types import ToolTrace


class ToolGateway:
    """Unified entrypoint for tool metadata and execution."""

    def __init__(self, registry: ToolRegistry, *, tag_results: bool = True):
        self.registry = registry
        self._tag_results = tag_results

    def definitions(self) -> list[dict[str, Any]]:
        return self.registry.get_definitions()

    async def invoke(self, name: str, arguments: dict[str, Any]) -> tuple[str, ToolTrace]:
        result = await self.registry.execute(name, arguments)
        preview = result if len(result) <= 200 else result[:200] + "..."
        trace = ToolTrace(
            name=name,
            arguments=arguments,
            result_preview=preview,
            ok=not result.startswith("Error"),
        )
        if self._tag_results:
            # Lazy import to avoid circular dependency:
            # adapters.tools -> agent.prompt_guard -> agent.__init__ -> agent.loop -> adapters.tools
            from snapagent.agent.prompt_guard import ContentTagger

            result = ContentTagger.wrap_tool_result(result, name)
        return result, trace
