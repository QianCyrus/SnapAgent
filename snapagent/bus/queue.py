"""Async message queue for decoupled channel-agent communication."""

import asyncio
from typing import Awaitable, Callable

from snapagent.bus.events import InboundMessage, OutboundMessage
from snapagent.core.types import DiagnosticEvent

EventEmitter = Callable[[DiagnosticEvent], Awaitable[None]]


class MessageBus:
    """
    Async message bus that decouples chat channels from the agent core.

    Channels push messages to the inbound queue, and the agent processes
    them and pushes responses to the outbound queue.
    """

    def __init__(self, event_emitter: EventEmitter | None = None):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        self._event_channels: dict[str, asyncio.Queue[str]] = {}
        self._event_emitter = event_emitter

    def set_event_emitter(self, event_emitter: EventEmitter | None) -> None:
        """Install or replace diagnostic event emitter."""
        self._event_emitter = event_emitter

    async def _emit(self, event: DiagnosticEvent) -> None:
        if not self._event_emitter:
            return
        try:
            await self._event_emitter(event)
        except Exception:
            # Observability must never block message flow.
            return

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Publish a message from a channel to the agent."""
        await self.inbound.put(msg)
        await self._emit(
            DiagnosticEvent(
                name="inbound.received",
                component="bus.queue",
                status="ok",
                session_key=msg.session_key,
                channel=msg.channel,
                chat_id=msg.chat_id,
                run_id=msg.run_id,
                turn_id=msg.turn_id,
            )
        )

    async def consume_inbound(self) -> InboundMessage:
        """Consume the next inbound message (blocks until available)."""
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Publish a response from the agent to channels."""
        await self.outbound.put(msg)
        await self._emit(
            DiagnosticEvent(
                name="outbound.published",
                component="bus.queue",
                status="ok",
                channel=msg.channel,
                chat_id=msg.chat_id,
                run_id=msg.run_id,
                turn_id=msg.turn_id,
            )
        )

    async def consume_outbound(self) -> OutboundMessage:
        """Consume the next outbound message (blocks until available)."""
        return await self.outbound.get()

    def drain_progress(self, chat_id: str) -> None:
        """Remove queued progress messages for a specific chat."""
        remaining: list[OutboundMessage] = []
        while not self.outbound.empty():
            try:
                msg = self.outbound.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not (msg.chat_id == chat_id and msg.metadata.get("_progress")):
                remaining.append(msg)
        for msg in remaining:
            self.outbound.put_nowait(msg)

    @property
    def inbound_size(self) -> int:
        """Number of pending inbound messages."""
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """Number of pending outbound messages."""
        return self.outbound.qsize()

    async def publish_event(self, session_key: str, content: str) -> None:
        """Publish an event to a session-specific event queue."""
        if session_key not in self._event_channels:
            self._event_channels[session_key] = asyncio.Queue()
        await self._event_channels[session_key].put(content)
        channel, chat_id = (session_key.split(":", 1) + [None])[:2]
        await self._emit(
            DiagnosticEvent(
                name="session.event.published",
                component="bus.queue",
                status="ok",
                session_key=session_key,
                channel=channel,
                chat_id=chat_id,
                attrs={"content": content},
            )
        )

    async def check_events(self, session_key: str) -> str | None:
        """Drain accumulated events for a session without blocking."""
        queue = self._event_channels.get(session_key)
        if not queue:
            return None

        events: list[str] = []
        while not queue.empty():
            try:
                events.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        return "\n".join(f"- {event}" for event in events) if events else None
