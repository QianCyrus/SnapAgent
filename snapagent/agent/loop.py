"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from uuid import uuid4

from loguru import logger

from snapagent.adapters.provider import ProviderAdapter
from snapagent.adapters.tools import ToolGateway
from snapagent.agent.context import ContextBuilder
from snapagent.agent.memory import MemoryStore
from snapagent.agent.subagent import SubagentManager
from snapagent.agent.tools.cron import CronTool
from snapagent.agent.tools.doctor import DoctorCheckTool
from snapagent.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from snapagent.agent.tools.message import MessageTool
from snapagent.agent.tools.rag import RagQueryTool
from snapagent.agent.tools.registry import ToolRegistry
from snapagent.agent.tools.shell import ExecTool
from snapagent.agent.tools.spawn import SpawnTool
from snapagent.agent.tools.web import WebFetchTool, WebSearchTool
from snapagent.bus.events import InboundMessage, OutboundMessage
from snapagent.bus.queue import MessageBus
from snapagent.core.compression import ContextCompressor
from snapagent.orchestrator.conversation import ConversationOrchestrator
from snapagent.providers.base import LLMProvider
from snapagent.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from snapagent.config.schema import ChannelsConfig, CompressionConfig, ExecToolConfig
    from snapagent.cron.service import CronService


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        brave_api_key: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        compression_config: CompressionConfig | None = None,
        enable_event_handling: bool = False,
        consolidation_interval: int = 0,
        enable_content_tagging: bool = True,
    ):
        from snapagent.config.schema import CompressionConfig, ExecToolConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.compression_config = compression_config or CompressionConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self.enable_event_handling = enable_event_handling
        self.consolidation_interval = consolidation_interval

        self.context = ContextBuilder(workspace, enable_content_tagging=enable_content_tagging)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: dict[str, asyncio.Lock] = {}
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> all scheduled tasks
        self._doctor_tasks: dict[str, asyncio.Task] = {}  # session_key -> active doctor diag task
        self._processing_tasks: set[str] = set()  # Session keys currently being processed
        self._processing_lock = asyncio.Lock()
        self._register_default_tools()
        self._provider_adapter = ProviderAdapter(
            provider=self.provider,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        self._tool_gateway = ToolGateway(self.tools, tag_results=enable_content_tagging)
        self._orchestrator = ConversationOrchestrator(
            provider=self._provider_adapter,
            tools=self._tool_gateway,
            max_iterations=self.max_iterations,
        )
        self._compressor = ContextCompressor.from_config(self.compression_config)

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
                extra_deny_patterns=getattr(self.exec_config, "extra_deny_patterns", None),
            )
        )
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(
            RagQueryTool(
                provider=self.provider,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
        )
        self.tools.register(DoctorCheckTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from snapagent.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id, message_id)

        if spawn_tool := self.tools.get("spawn"):
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(channel, chat_id)

        if cron_tool := self.tools.get("cron"):
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(channel, chat_id)

    def _build_initial_messages(
        self,
        *,
        history: list[dict[str, Any]],
        current_message: str,
        channel: str,
        chat_id: str,
        media: list[str] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Build model input with compressed history and optional compression hint."""
        compressed = self._compressor.compress(history)
        messages = self.context.build_messages(
            history=compressed.raw_recent,
            current_message=current_message,
            media=media,
            channel=channel,
            chat_id=chat_id,
            enable_event_handling=self.enable_event_handling,
        )
        hint = self._compressor.render_context_hint(compressed)
        if hint:
            # Insert hint right before runtime metadata + user message.
            messages.insert(max(1, len(messages) - 2), {"role": "user", "content": hint})
        return messages, compressed.token_budget_report

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        session_key: str | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run one orchestrated turn. Returns (final_content, tools_used, messages)."""
        async def _inject_event(messages: list[dict]) -> bool:
            if not session_key:
                return False
            event = await self.bus.check_events(session_key)
            if not event:
                return False
            flattened_event = self._flatten_interrupt_events(event)
            messages.append(
                {
                    "role": "system",
                    "content": f"<SYS_EVENT type=\"user_interrupt\">{event}</SYS_EVENT>",
                }
            )
            if flattened_event:
                messages.append({"role": "user", "content": flattened_event})
            return True

        async def _before_model(messages: list[dict]) -> None:
            await _inject_event(messages)

        async def _before_tool(messages: list[dict], _index: int, _tool_calls: list) -> bool:
            return await _inject_event(messages)

        result = await self._orchestrator.run_agent_loop(
            initial_messages=initial_messages,
            on_progress=on_progress,
            before_model=_before_model,
            before_tool=_before_tool,
        )
        tools_used = [t.name for t in result.tool_trace]
        return result.final_text, tools_used, result.messages

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            raw = msg.content.strip()
            parts = raw.split(maxsplit=1)
            command = parts[0].lower() if parts else ""
            if command == "/stop":
                await self._handle_stop(msg)
            elif command == "/doctor":
                await self._handle_doctor(msg)
            else:
                if self.enable_event_handling and msg.session_key in self._processing_tasks:
                    await self.bus.publish_event(msg.session_key, msg.content)
                    logger.info("Published interrupt event for session {}", msg.session_key)
                    continue

                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._cleanup_task(k, t))

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        run_id, turn_id = self._ensure_correlation(msg)
        total = await self._cancel_session_tasks(msg.session_key, msg.chat_id)
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=content,
                run_id=run_id,
                turn_id=turn_id,
            )
        )

    async def _handle_doctor(self, msg: InboundMessage) -> None:
        """Handle /doctor commands in a dedicated, session-scoped lifecycle."""
        run_id, turn_id = self._ensure_correlation(msg)
        key = msg.session_key
        session = self.sessions.get_or_create(key)
        text = msg.content.strip()
        lowered = text.lower()
        parts = lowered.split(maxsplit=2)
        action = parts[1] if len(parts) > 1 else "start"

        if action == "status":
            task = self._doctor_tasks.get(key)
            task_status = "running" if task and not task.done() else "idle"
            mode = "on" if session.metadata.get("doctor_mode") else "off"
            codex_session = session.metadata.get("doctor_codex_session_id") or "-"
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"🩺 Doctor status: {task_status} (mode={mode}, codex_session={codex_session}).",
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
            return

        if action == "cancel":
            total = await self._cancel_session_tasks(key, msg.chat_id)
            session.metadata.pop("doctor_mode", None)
            session.metadata.pop("doctor_codex_session_id", None)
            self.sessions.save(session)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"🩺 Doctor cancelled. Stopped {total} task(s).",
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
            return

        if action == "resume":
            session.metadata.pop("doctor_mode", None)
            session.metadata.pop("doctor_codex_session_id", None)
            self.sessions.save(session)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="▶️ Doctor mode OFF. Conversation resumed.",
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
            return

        note = text[len("/doctor") :].strip() if text.lower().startswith("/doctor") else ""
        total = await self._cancel_session_tasks(key, msg.chat_id)
        session.metadata.pop("doctor_codex_session_id", None)
        guidance = self._doctor_setup_guidance()
        if guidance:
            session.metadata.pop("doctor_mode", None)
            self.sessions.save(session)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        f"🩺 Doctor precheck blocked (stopped {total} task(s)).\n\n"
                        f"{guidance}"
                    ),
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
            return

        session.metadata["doctor_mode"] = True
        self.sessions.save(session)

        await self.bus.publish_outbound(
            OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"🩺 Doctor mode ON. Stopped {total} task(s). Running diagnostics...",
                run_id=run_id,
                turn_id=turn_id,
            )
        )

        bootstrap = note or (
            "Please self-diagnose this session. Collect evidence with doctor_check "
            "(health/status/logs/events) before conclusions."
        )
        if self._doctor_cli_available():
            task = asyncio.create_task(
                self._run_doctor_via_codex_cli(
                    msg=msg,
                    prompt=bootstrap,
                    run_id=run_id,
                    turn_id=turn_id,
                    session_key=key,
                )
            )
        else:
            logger.warning("Codex CLI unavailable; falling back to provider-based doctor flow")
            follow_up = InboundMessage(
                channel=msg.channel,
                sender_id=msg.sender_id,
                chat_id=msg.chat_id,
                content=bootstrap,
                media=[],
                metadata=dict(msg.metadata or {}),
                session_key_override=msg.session_key_override,
            )
            task = asyncio.create_task(self._dispatch(follow_up))
        self._doctor_tasks[key] = task
        self._active_tasks.setdefault(key, []).append(task)
        task.add_done_callback(lambda t, k=key: self._cleanup_task(k, t))

    def _doctor_cli_available(self) -> bool:
        """Return whether `codex` CLI is available on PATH."""
        return shutil.which("codex") is not None

    def _doctor_codex_model(self) -> str:
        """Resolve doctor Codex CLI model from env with a stable default."""
        model = os.environ.get("SNAPAGENT_DOCTOR_CODEX_MODEL", "").strip()
        return model or "gpt-5.3-codex"

    def _build_doctor_codex_command(
        self, prompt: str, *, resume_session_id: str | None = None
    ) -> list[str]:
        """Build Codex CLI command for doctor diagnostics."""
        if resume_session_id:
            return [
                "codex",
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
                "--model",
                self._doctor_codex_model(),
                "-c",
                'approval_policy="never"',
                "-c",
                'model_reasoning_effort="high"',
                resume_session_id,
                prompt,
            ]
        return [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--model",
            self._doctor_codex_model(),
            "--sandbox",
            "workspace-write",
            "--full-auto",
            "-c",
            'approval_policy="never"',
            "-c",
            'model_reasoning_effort="high"',
            prompt,
        ]

    async def _run_doctor_via_codex_cli(
        self,
        *,
        msg: InboundMessage,
        prompt: str,
        run_id: str,
        turn_id: str,
        session_key: str | None = None,
    ) -> None:
        """Run doctor diagnostics through Codex CLI and publish final result."""
        resume_session_id = self._get_doctor_codex_session_id(session_key) if session_key else None
        cmd = self._build_doctor_codex_command(prompt, resume_session_id=resume_session_id)
        proc: asyncio.subprocess.Process | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )
        except FileNotFoundError:
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "🩺 Doctor failed: codex CLI not found on PATH. "
                        "Please install Codex CLI or use provider-based diagnostics."
                    ),
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
            return
        except Exception as e:
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"🩺 Doctor failed to start codex CLI: {e}",
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
            return

        try:
            output, session_id = await self._read_codex_cli_output(proc.stdout)
            exit_code = await proc.wait()
            stderr_text = ""
            if proc.stderr is not None:
                stderr_text = (await proc.stderr.read()).decode("utf-8", "replace").strip()

            if exit_code == 0:
                final = output or "Doctor completed via Codex CLI, but no final message was captured."
            else:
                detail = stderr_text or output or f"exited with code {exit_code}"
                final = f"🩺 Doctor via Codex CLI failed: {detail}"

            if session_id:
                if session_key:
                    self._set_doctor_codex_session_id(session_key, session_id)
                final = f"{final}\n\n(codex session: {session_id})"

            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=final,
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )
        except asyncio.CancelledError:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()
            raise
        except Exception as e:
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"🩺 Doctor via Codex CLI errored: {e}",
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )

    def _get_doctor_codex_session_id(self, session_key: str) -> str | None:
        """Get stored Codex session ID for a doctor-mode chat session."""
        session = self.sessions.get_or_create(session_key)
        raw = session.metadata.get("doctor_codex_session_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    def _set_doctor_codex_session_id(self, session_key: str, session_id: str) -> None:
        """Persist Codex session ID for doctor-mode resume calls."""
        if not session_id.strip():
            return
        session = self.sessions.get_or_create(session_key)
        session.metadata["doctor_codex_session_id"] = session_id.strip()
        self.sessions.save(session)

    async def _read_codex_cli_output(
        self, stream: asyncio.StreamReader | None
    ) -> tuple[str | None, str | None]:
        """Read Codex `--json` stdout and return (assistant_message, session_id)."""
        if stream is None:
            return None, None

        last_message: str | None = None
        session_id: str | None = None

        while True:
            line = await stream.readline()
            if not line:
                break

            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue

            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id")
                if isinstance(thread_id, str) and thread_id.strip():
                    session_id = thread_id.strip()
                continue

            if event.get("type") == "item.completed" and isinstance(event.get("item"), dict):
                item = event["item"]
                msg = ""
                if item.get("type") == "message":
                    content_parts = item.get("content", [])
                    texts = [
                        p.get("text", "")
                        for p in content_parts
                        if isinstance(p, dict) and p.get("type") == "output_text"
                    ]
                    msg = "\n".join(texts).strip()
                elif item.get("type") == "agent_message":
                    msg = str(item.get("text", "")).strip()
                if msg:
                    last_message = msg
                continue

            if (
                event.get("type") == "response_item"
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("type") == "message"
                and event["payload"].get("role") == "assistant"
            ):
                content_parts = event["payload"].get("content", [])
                texts = [
                    p.get("text", "")
                    for p in content_parts
                    if isinstance(p, dict) and p.get("type") == "output_text"
                ]
                msg = "\n".join(texts).strip()
                if msg:
                    last_message = msg

        return last_message, session_id

    async def _cancel_session_tasks(self, session_key: str, chat_id: str) -> int:
        """Cancel all active tasks, doctor task, and subagents for one session."""
        tasks = self._active_tasks.pop(session_key, [])
        doctor_task = self._doctor_tasks.get(session_key)
        if doctor_task and doctor_task not in tasks:
            tasks.append(doctor_task)

        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        self._doctor_tasks.pop(session_key, None)
        sub_cancelled = await self.subagents.cancel_by_session(session_key)
        self.bus.drain_progress(chat_id)
        return cancelled + sub_cancelled

    def _doctor_setup_guidance(self) -> str | None:
        """Return setup guidance when no usable model provider is configured."""
        try:
            from snapagent.config.loader import get_config_path, load_config
            from snapagent.observability.health import collect_health_snapshot
        except Exception:
            return None

        try:
            config_path = get_config_path()
            config = load_config()
            snapshot = collect_health_snapshot(config=config, config_path=config_path).to_dict(deep=True)
            provider = next(
                (item for item in snapshot.get("evidence", []) if item.get("component") == "provider"),
                None,
            )
            if not provider:
                return None
            if provider.get("status") in {"ok", "degraded"}:
                return None

            details = provider.get("details", {})
            model = details.get("model") or config.agents.defaults.model
            provider_name = details.get("provider") or config.get_provider_name(model) or "unknown"

            lines = [
                "Doctor needs a working LLM provider before diagnostics can run.",
                f"- model: {model}",
                f"- provider: {provider_name}",
                "",
                "Try one of these setup paths:",
                "1. Codex OAuth: snapagent provider login openai-codex",
                "2. API key config: edit ~/.snapagent/config.json -> providers.<name>.apiKey",
                "3. Verify: snapagent health --deep --json",
                "4. Retry in chat: /doctor",
            ]
            return "\n".join(lines)
        except Exception:
            # Setup hint should not break doctor flow.
            return None

    def _cleanup_task(self, session_key: str, task: asyncio.Task) -> None:
        """Remove a completed task from active tracking."""
        tasks = self._active_tasks.get(session_key)
        if tasks and task in tasks:
            tasks.remove(task)
            if not tasks:
                del self._active_tasks[session_key]
        if self._doctor_tasks.get(session_key) is task:
            self._doctor_tasks.pop(session_key, None)

    @staticmethod
    def _flatten_interrupt_events(raw_events: str) -> str:
        """Convert queued event bullet list into plain user message text."""
        lines: list[str] = []
        for line in raw_events.splitlines():
            text = line.strip()
            if text.startswith("- "):
                text = text[2:]
            if text:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _ensure_correlation(msg: InboundMessage) -> tuple[str, str]:
        """Guarantee run/turn correlation IDs on inbound messages."""
        metadata = msg.metadata or {}
        if msg.metadata is None:
            msg.metadata = metadata
        run_id = msg.run_id or metadata.get("run_id") or uuid4().hex
        turn_id = msg.turn_id or metadata.get("turn_id") or uuid4().hex[:12]
        msg.run_id = run_id
        msg.turn_id = turn_id
        metadata["run_id"] = run_id
        metadata["turn_id"] = turn_id
        return run_id, turn_id

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        self._processing_tasks.add(msg.session_key)
        try:
            async with self._processing_lock:
                try:
                    response = await self._process_message(msg)
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await self.bus.publish_outbound(
                            OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="",
                                metadata=msg.metadata or {},
                                run_id=msg.run_id,
                                turn_id=msg.turn_id,
                            )
                        )
                except asyncio.CancelledError:
                    logger.info("Task cancelled for session {}", msg.session_key)
                    raise
                except Exception:
                    logger.exception("Error processing message for session {}", msg.session_key)
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="Sorry, I encountered an error.",
                            run_id=msg.run_id,
                            turn_id=msg.turn_id,
                        )
                    )
        finally:
            self._processing_tasks.discard(msg.session_key)
            if self.enable_event_handling:
                pending = await self.bus.check_events(msg.session_key)
                if pending:
                    follow_up_content = self._flatten_interrupt_events(pending)
                    if not follow_up_content:
                        return
                    follow_up = InboundMessage(
                        channel=msg.channel,
                        sender_id=msg.sender_id,
                        chat_id=msg.chat_id,
                        content=follow_up_content,
                        media=[],
                        metadata=dict(msg.metadata or {}),
                        session_key_override=msg.session_key_override,
                    )
                    task = asyncio.create_task(self._dispatch(follow_up))
                    self._active_tasks.setdefault(follow_up.session_key, []).append(task)
                    task.add_done_callback(
                        lambda t, k=follow_up.session_key: self._cleanup_task(k, t)
                    )
                    logger.info(
                        "Replayed queued interrupt event(s) as follow-up for session {}",
                        msg.session_key,
                    )

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._consolidation_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._consolidation_locks[session_key] = lock
        return lock

    def _prune_consolidation_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Drop lock entry if no longer in use."""
        if not lock.locked():
            self._consolidation_locks.pop(session_key, None)

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        run_id, turn_id = self._ensure_correlation(msg)

        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages, _compression_report = self._build_initial_messages(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages, session_key=key)
            persist_start = max(0, len(messages) - 2)
            self._save_turn(session, all_msgs, persist_start)
            self.sessions.save(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
                run_id=run_id,
                turn_id=turn_id,
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._get_consolidation_lock(session.key)
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated :]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                                run_id=run_id,
                                turn_id=turn_id,
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                    run_id=run_id,
                    turn_id=turn_id,
                )
            finally:
                self._consolidating.discard(session.key)
                self._prune_consolidation_lock(session.key, lock)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="New session started.",
                run_id=run_id,
                turn_id=turn_id,
            )
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "🐈 snapagent commands:\n"
                    "/new — Start a new conversation\n"
                    "/plan — Switch to plan mode (think first, then act)\n"
                    "/normal — Switch to normal mode (execute directly)\n"
                    "/stop — Stop the current task\n"
                    "/doctor — Pause current session and start diagnostics\n"
                    "/doctor status — Show doctor task status\n"
                    "/doctor cancel — Cancel running diagnostics\n"
                    "/doctor resume — Exit doctor mode\n"
                    "/help — Show available commands"
                ),
                run_id=run_id,
                turn_id=turn_id,
            )

        if cmd == "/plan":
            session.metadata["plan_mode"] = True
            self.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "\U0001f4cb Plan mode ON\n"
                    "I'll clarify requirements and present a plan for your approval "
                    "before taking any action.\n"
                    "Use /normal to switch back to direct execution."
                ),
                run_id=run_id,
                turn_id=turn_id,
            )
        if cmd == "/normal":
            session.metadata.pop("plan_mode", None)
            self.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "\u26a1 Normal mode — I'll execute tools directly.\n"
                    "Use /plan to switch back."
                ),
                run_id=run_id,
                turn_id=turn_id,
            )

        plan_mode = session.metadata.get("plan_mode", False)
        if plan_mode:
            msg = InboundMessage(
                channel=msg.channel,
                sender_id=msg.sender_id,
                chat_id=msg.chat_id,
                content=(
                    "[Plan Mode] First clarify the requirements, then present a structured plan "
                    "and WAIT for the user to approve, modify, or reject it before executing.\n\n"
                    + msg.content
                ),
                timestamp=msg.timestamp,
                media=msg.media,
                metadata=msg.metadata,
                session_key_override=msg.session_key_override,
                run_id=run_id,
                turn_id=turn_id,
            )
        elif session.metadata.get("doctor_mode") and not cmd.startswith("/"):
            doctor_prompt = (
                "[Doctor Mode] Diagnose issues using evidence first. "
                "Use doctor_check with check=health/status/logs/events as needed. "
                "Cite observed evidence and then propose next actions.\n\n"
                + msg.content
            )
            if self._doctor_cli_available():
                await self._run_doctor_via_codex_cli(
                    msg=msg,
                    prompt=doctor_prompt,
                    run_id=run_id,
                    turn_id=turn_id,
                    session_key=key,
                )
                return None

            msg = InboundMessage(
                channel=msg.channel,
                sender_id=msg.sender_id,
                chat_id=msg.chat_id,
                content=doctor_prompt,
                timestamp=msg.timestamp,
                media=msg.media,
                metadata=msg.metadata,
                session_key_override=msg.session_key_override,
                run_id=run_id,
                turn_id=turn_id,
            )

        consolidation_threshold = self.consolidation_interval or self.memory_window
        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated >= consolidation_threshold and session.key not in self._consolidating:
            self._consolidating.add(session.key)
            lock = self._get_consolidation_lock(session.key)

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    self._prune_consolidation_lock(session.key, lock)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.memory_window)
        initial_messages, compression_report = self._build_initial_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            meta["run_id"] = run_id
            meta["turn_id"] = turn_id
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                    run_id=run_id,
                    turn_id=turn_id,
                )
            )

        on_progress = on_progress or _bus_progress
        if plan_mode:
            await on_progress("\U0001f4cb Plan mode — thinking before acting...")

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress,
            session_key=key,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        logger.debug("Compression report: {}", compression_report)

        persist_start = max(0, len(initial_messages) - 2)
        self._save_turn(session, all_msgs, persist_start)
        self.sessions.save(session)

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return None

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata={
                **(msg.metadata or {}),
                "run_id": run_id,
                "turn_id": turn_id,
            },
            run_id=run_id,
            turn_id=turn_id,
        )

    _TOOL_RESULT_MAX_CHARS = 500

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime

        for m in messages[skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str):
                content = entry["content"]
                if len(content) > self._TOOL_RESULT_MAX_CHARS:
                    entry["content"] = content[: self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            if entry.get("role") == "user" and isinstance(entry.get("content"), list):
                entry["content"] = [
                    {"type": "text", "text": "[image]"}
                    if (
                        c.get("type") == "image_url"
                        and c.get("image_url", {}).get("url", "").startswith("data:image/")
                    )
                    else c
                    for c in entry["content"]
                ]
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session,
            self.provider,
            self.model,
            archive_all=archive_all,
            memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        return response.content if response else ""
