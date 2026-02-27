"""Agent core module."""

# Lazy re-exports to avoid circular imports.
# Users should import directly from submodules:
#   from snapagent.agent.loop import AgentLoop
#   from snapagent.agent.context import ContextBuilder
#   etc.


def __getattr__(name: str):
    if name == "AgentLoop":
        from snapagent.agent.loop import AgentLoop

        return AgentLoop
    if name == "ContextBuilder":
        from snapagent.agent.context import ContextBuilder

        return ContextBuilder
    if name == "MemoryStore":
        from snapagent.agent.memory import MemoryStore

        return MemoryStore
    if name == "SkillsLoader":
        from snapagent.agent.skills import SkillsLoader

        return SkillsLoader
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader"]
