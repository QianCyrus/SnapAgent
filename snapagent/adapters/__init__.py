"""Adapter layer for external dependencies."""


def __getattr__(name: str):
    if name == "ProviderAdapter":
        from snapagent.adapters.provider import ProviderAdapter

        return ProviderAdapter
    if name == "ToolGateway":
        from snapagent.adapters.tools import ToolGateway

        return ToolGateway
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ProviderAdapter", "ToolGateway"]
