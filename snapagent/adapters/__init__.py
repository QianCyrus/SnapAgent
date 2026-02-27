"""Adapter layer for external dependencies."""

from snapagent.adapters.provider import ProviderAdapter
from snapagent.adapters.tools import ToolGateway

__all__ = ["ProviderAdapter", "ToolGateway"]
