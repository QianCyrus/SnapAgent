"""Conversation orchestration independent from channel/runtime concerns."""

from __future__ import annotations

import json
import re
from typing import Awaitable, Callable

from loguru import logger

from snapagent.adapters.provider import ProviderAdapter
from snapagent.adapters.tools import ToolGateway
from snapagent.core.types import AgentResult, ReactStep, ReactTrace, ToolTrace
from snapagent.orchestrator.dedup import ToolCallDedup
from snapagent.utils.think_strip import ThinkTagStripper

# Module-level stripper instance (stateless, safe to share).
_think_stripper = ThinkTagStripper()

# Friendly display labels for built-in tools: (emoji, label)
_TOOL_DISPLAY: dict[str, tuple[str, str]] = {
    "web_search": ("\U0001f50d", "Searching"),
    "web_fetch": ("\U0001f310", "Fetching page"),
    "read_file": ("\U0001f4d6", "Reading file"),
    "write_file": ("\u270f\ufe0f", "Writing file"),
    "edit_file": ("\U0001f4dd", "Editing file"),
    "list_dir": ("\U0001f4c2", "Listing dir"),
    "exec": ("\u26a1", "Running command"),
    "message": ("\U0001f4ac", "Sending message"),
    "cron": ("\u23f0", "Scheduling"),
    "spawn": ("\U0001f504", "Spawning subtask"),
    "rag_query": ("\U0001f9ea", "Fact-checking"),
}

_OBSERVATION_PREVIEW_LEN = 200


class ConversationOrchestrator:
    """Run model/tool iterations and return normalized turn results."""

    def __init__(self, provider: ProviderAdapter, tools: ToolGateway, *, max_iterations: int = 40):
        self.provider = provider
        self.tools = tools
        self.max_iterations = max_iterations

    async def run_agent_loop(
        self,
        initial_messages: list[dict],
        *,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        before_model: Callable[[list[dict]], Awaitable[None]] | None = None,
        before_tool: Callable[[list[dict], int, list], Awaitable[bool]] | None = None,
    ) -> AgentResult:
        messages = list(initial_messages)
        iteration = 0
        final_content: str | None = None
        tool_trace: list[ToolTrace] = []
        react_steps: list[ReactStep] = []
        usage: dict[str, int] = {}
        dedup = ToolCallDedup()

        while iteration < self.max_iterations:
            iteration += 1

            if before_model:
                await before_model(messages)

            # Hard-cap guarantee: even provider exceptions count toward budget.
            try:
                response = await self.provider.chat(
                    messages=messages, tools=self.tools.definitions()
                )
            except Exception:
                logger.exception("LLM call failed at iteration {}", iteration)
                break

            usage = self._merge_usage(usage, response.usage)

            if response.has_tool_calls:
                # --- Thought ---
                thought = self._strip_think(response.content)

                if on_progress:
                    if thought:
                        plan = self._extract_plan(thought)
                        if plan:
                            await on_progress(f"\U0001f4cb {plan}")
                        else:
                            await on_progress(thought)
                    await on_progress(
                        self._tool_hint(response.tool_calls, step=iteration), tool_hint=True
                    )

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": tool_call_dicts,
                        "reasoning_content": response.reasoning_content,
                    }
                )

                # --- Actions + Observations ---
                step_traces: list[ToolTrace] = []
                step_observations: list[str] = []
                interrupted = False

                for index, tool_call in enumerate(response.tool_calls):
                    if before_tool and await before_tool(messages, index, response.tool_calls):
                        for cancelled in response.tool_calls[index:]:
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": cancelled.id,
                                    "name": cancelled.name,
                                    "content": "CANCELLED: User interrupted",
                                }
                            )
                        interrupted = True
                        break

                    if isinstance(tool_call.arguments, dict):
                        args = tool_call.arguments
                    elif isinstance(tool_call.arguments, str):
                        try:
                            parsed = json.loads(tool_call.arguments)
                            args = parsed if isinstance(parsed, dict) else {}
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = {}

                    # Hard-block: if search cap reached, refuse further searches.
                    if tool_call.name == "web_search" and dedup.search_cap_reached:
                        result = (
                            "[System] Search limit reached. You have already performed "
                            f"{dedup.total_search_count} searches this turn. "
                            "Use the results you already have to answer the question. "
                            "If you need more detail, use web_fetch on a URL from "
                            "your existing results."
                        )
                        trace = ToolTrace(
                            name=tool_call.name,
                            arguments=args,
                            result_preview="[blocked: search cap]",
                            ok=False,
                        )
                    else:
                        dup = dedup.check(tool_call.name, args)
                        if dup.is_duplicate:
                            result = dup.cached_result or ""
                            trace = ToolTrace(
                                name=tool_call.name,
                                arguments=args,
                                result_preview="[cached: duplicate query]",
                                ok=True,
                            )
                        else:
                            result, trace = await self.tools.invoke(tool_call.name, args)
                            dedup.store(tool_call.name, args, result)

                    dedup.record_tool_name(tool_call.name)
                    tool_trace.append(trace)
                    step_traces.append(trace)
                    step_observations.append(
                        result[:_OBSERVATION_PREVIEW_LEN]
                        if len(result) > _OBSERVATION_PREVIEW_LEN
                        else result
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        }
                    )

                react_steps.append(
                    ReactStep(
                        iteration=iteration,
                        thought=thought,
                        actions=step_traces,
                        observations=step_observations,
                    )
                )

                if dedup.search_loop_detected and not interrupted:
                    history = dedup.search_history_summary()
                    messages.append({
                        "role": "user",
                        "content": (
                            "[System] STOP SEARCHING. You have called web_search "
                            f"{dedup.consecutive_search_count} times consecutively. "
                            "You already have sufficient search results to answer.\n\n"
                            f"{history}\n\n"
                            "Synthesize your answer NOW from the results above. "
                            "If you need more detail on a specific page, use web_fetch "
                            "instead of searching again."
                        ),
                    })
            else:
                clean = self._strip_think(response.content) or ""
                messages.append(
                    {
                        "role": "assistant",
                        "content": clean,
                        "reasoning_content": response.reasoning_content,
                    }
                )
                final_content = clean
                react_steps.append(ReactStep(iteration=iteration, thought=clean))
                break

        hit_cap = final_content is None
        if hit_cap:
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        react_trace = ReactTrace(steps=react_steps, hit_iteration_cap=hit_cap)

        return AgentResult(
            final_text=final_content,
            tool_trace=tool_trace,
            react_trace=react_trace,
            usage=usage,
            diagnostics={
                "iterations": iteration,
                "tool_calls": len(tool_trace),
                "react_steps": len(react_steps),
            },
            messages=messages,
        )

    @staticmethod
    def _merge_usage(base: dict[str, int], delta: dict[str, int]) -> dict[str, int]:
        if not delta:
            return base
        merged = dict(base)
        for key, value in delta.items():
            merged[key] = int(merged.get(key, 0)) + int(value)
        return merged

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        return _think_stripper.strip(text)

    _PLAN_RE = re.compile(r"\*\*Plan:\*\*\n((?:\d+\.\s*\[[ x]\].*\n?)+)", re.IGNORECASE)

    @staticmethod
    def _extract_plan(text: str | None) -> str | None:
        """Extract a plan block from assistant text, if present."""
        if not text:
            return None
        m = ConversationOrchestrator._PLAN_RE.search(text)
        return m.group(0).strip() if m else None

    @staticmethod
    def _tool_hint(tool_calls: list, step: int = 0) -> str:
        def _fmt(tc):
            emoji, label = _TOOL_DISPLAY.get(tc.name, ("\U0001f527", tc.name))
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if isinstance(val, str) and val:
                short = val[:60] + "\u2026" if len(val) > 60 else val
                return f"{emoji} {label}: {short}"
            return f"{emoji} {label}"

        prefix = f"[Step {step}] " if step else ""
        return prefix + " | ".join(_fmt(tc) for tc in tool_calls)
