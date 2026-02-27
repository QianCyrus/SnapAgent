"""Message bus module for decoupled channel-agent communication."""

from snapagent.bus.events import InboundMessage, OutboundMessage
from snapagent.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
