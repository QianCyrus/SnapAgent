"""JSONL sink for diagnostic events."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from snapagent.core.types import DiagnosticEvent
from snapagent.observability.redaction import redact_payload


class JsonlLoggingSink:
    """Append-only JSONL sink with basic rotation and filtering."""

    def __init__(
        self,
        path: Path,
        rotate_bytes: int = 5 * 1024 * 1024,
        max_backups: int = 3,
    ) -> None:
        self.path = path
        self.rotate_bytes = rotate_bytes
        self.max_backups = max(0, max_backups)
        self._lock = asyncio.Lock()

    async def emit(self, event: DiagnosticEvent | dict[str, Any]) -> None:
        """Append a redacted diagnostic event to the log."""
        payload = event.to_dict() if isinstance(event, DiagnosticEvent) else dict(event)
        redacted = redact_payload(payload)
        line = json.dumps(redacted, ensure_ascii=False)

        async with self._lock:
            await asyncio.to_thread(self._append_line_sync, line)

    def _append_line_sync(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (line + "\n").encode("utf-8")
        if self.path.exists() and self.path.stat().st_size + len(encoded) > self.rotate_bytes:
            self._rotate_sync()
        with self.path.open("ab") as handle:
            handle.write(encoded)

    def _rotate_sync(self) -> None:
        if self.max_backups <= 0:
            if self.path.exists():
                self.path.unlink()
            return

        oldest = self.path.with_suffix(f"{self.path.suffix}.{self.max_backups}")
        if oldest.exists():
            oldest.unlink()

        for index in range(self.max_backups - 1, 0, -1):
            src = self.path.with_suffix(f"{self.path.suffix}.{index}")
            dst = self.path.with_suffix(f"{self.path.suffix}.{index + 1}")
            if src.exists():
                src.replace(dst)

        if self.path.exists():
            self.path.replace(self.path.with_suffix(f"{self.path.suffix}.1"))

    def _iter_log_files(self) -> list[Path]:
        files: list[Path] = []
        for index in range(self.max_backups, 0, -1):
            candidate = self.path.with_suffix(f"{self.path.suffix}.{index}")
            if candidate.exists():
                files.append(candidate)
        if self.path.exists():
            files.append(self.path)
        return files

    @staticmethod
    def _matches(
        event: dict[str, Any],
        *,
        session_key: str | None,
        run_id: str | None,
    ) -> bool:
        if session_key and event.get("session_key") != session_key:
            return False
        if run_id and event.get("run_id") != run_id:
            return False
        return True

    @staticmethod
    def _decode_line(raw: str) -> dict[str, Any] | None:
        line = raw.strip()
        if not line:
            return None
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def query(
        self,
        *,
        session_key: str | None = None,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return latest matching events from JSONL logs."""
        if limit <= 0:
            return []

        rows: list[dict[str, Any]] = []
        for path in self._iter_log_files():
            with path.open(encoding="utf-8") as handle:
                for raw in handle:
                    event = self._decode_line(raw)
                    if not event:
                        continue
                    if self._matches(event, session_key=session_key, run_id=run_id):
                        rows.append(event)
                        if len(rows) > limit:
                            rows = rows[-limit:]
        return rows

    def follow(
        self,
        *,
        session_key: str | None = None,
        run_id: str | None = None,
        poll_interval: float = 0.5,
    ):
        """Yield new matching events in follow mode (tail -f style)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

        handle = self.path.open(encoding="utf-8")
        try:
            handle.seek(0, 2)
            while True:
                raw = handle.readline()
                if raw:
                    event = self._decode_line(raw)
                    if event and self._matches(event, session_key=session_key, run_id=run_id):
                        yield event
                    continue

                time.sleep(poll_interval)

                try:
                    latest = self.path.stat()
                except FileNotFoundError:
                    # Rotation may temporarily remove current file.
                    self.path.touch(exist_ok=True)
                    latest = self.path.stat()

                current = os.fstat(handle.fileno())

                rotated = (current.st_ino, current.st_dev) != (latest.st_ino, latest.st_dev)
                truncated = latest.st_size < handle.tell()

                if rotated:
                    handle.close()
                    handle = self.path.open(encoding="utf-8")
                    # Read from start of new active file to avoid dropping lines
                    # written between rotation and reopen.
                    handle.seek(0)
                elif truncated:
                    handle.seek(0)
        finally:
            handle.close()
