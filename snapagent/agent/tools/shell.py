"""Shell execution tool."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from snapagent.agent.tools.base import Tool
from snapagent.agent.tools.sandbox import CommandSanitizer


class ExecTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
        extra_deny_patterns: list[str] | None = None,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.path_append = path_append
        self._sanitizer = CommandSanitizer(
            extra_deny_patterns=extra_deny_patterns,
            allow_patterns=allow_patterns,
            restrict_to_workspace=restrict_to_workspace,
            workspace=Path(working_dir) if working_dir else None,
        )

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute"},
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        result = self._sanitizer.check(command, cwd)
        if not result.allowed:
            return f"Error: {result.reason}"

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                # Wait for the process to fully terminate so pipes are
                # drained and file descriptors are released.
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                return f"Error: Command timed out after {self.timeout} seconds"

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result_text = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            max_len = 10000
            if len(result_text) > max_len:
                result_text = (
                    result_text[:max_len]
                    + f"\n... (truncated, {len(result_text) - max_len} more chars)"
                )

            return result_text

        except Exception as e:
            return f"Error executing command: {str(e)}"
