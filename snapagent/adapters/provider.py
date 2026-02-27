"""Provider adapter that isolates model runtime parameters."""

from __future__ import annotations

from typing import Any

from snapagent.providers.base import LLMProvider, LLMResponse


class ProviderAdapter:
    """Thin adapter around LLMProvider with pinned runtime defaults."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
    ):
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return await self.provider.chat(
            messages=messages,
            tools=tools,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
