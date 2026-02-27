"""Chat channels module with plugin architecture."""

from snapagent.channels.base import BaseChannel
from snapagent.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
