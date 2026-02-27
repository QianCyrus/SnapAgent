"""Structured access to workspace memory files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from snapagent.utils.helpers import ensure_dir


class MemoryRepository:
    """Repository for long-term memory and searchable history."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(
        self,
        entry: str,
        *,
        topic_tags: list[str] | None = None,
        source_turn_range: str | None = None,
    ) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        tags = ", ".join(topic_tags or [])
        source = source_turn_range or ""
        block = (
            f"### entry_id: {entry_id}\n"
            f"- timestamp: {ts}\n"
            f"- topic_tags: {tags}\n"
            f"- source_turn_range: {source}\n\n"
            f"{entry.strip()}\n\n"
        )
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(block)

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        if not long_term:
            return ""
        return f"## Long-term Memory\n{long_term}"
