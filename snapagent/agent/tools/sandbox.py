"""Shell command security sandbox."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SanitizeResult:
    """Result of command sanitization."""

    allowed: bool
    reason: str | None = None


# Each tuple: (compiled pattern, human-readable reason).
_DEFAULT_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Destructive filesystem operations
    (re.compile(r"\brm\s+-[rf]{1,2}\b", re.I), "recursive delete"),
    (re.compile(r"\bdel\s+/[fq]\b", re.I), "Windows force delete"),
    (re.compile(r"\brmdir\s+/s\b", re.I), "Windows recursive rmdir"),
    (re.compile(r"(?:^|[;&|]\s*)format\b", re.I), "disk format"),
    (re.compile(r"\b(mkfs|diskpart)\b", re.I), "disk partitioning"),
    (re.compile(r"\bdd\s+if=", re.I), "raw disk write"),
    (re.compile(r">\s*/dev/sd", re.I), "write to block device"),
    # System power control
    (re.compile(r"\b(shutdown|reboot|poweroff|init\s+[06])\b", re.I), "system power control"),
    # Fork bombs
    (re.compile(r":\(\)\s*\{.*\};\s*:", re.I), "fork bomb"),
    (re.compile(r"\bfork\b.*\bwhile\b.*\btrue\b", re.I), "fork loop"),
    # Pipe-to-shell execution
    (
        re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash|zsh|dash)\b", re.I),
        "pipe-to-shell execution",
    ),
    # Dangerous permissions
    (re.compile(r"\bchmod\s+[0-7]*7[0-7]*\b", re.I), "world-writable permission"),
    (re.compile(r"\bchmod\s+\+s\b", re.I), "setuid bit"),
    # Credential exfiltration via network
    (
        re.compile(
            r"\b(curl|wget|nc|ncat)\b.*\$\{?"
            r"(API_KEY|SECRET|TOKEN|PASSWORD|CREDENTIALS)",
            re.I,
        ),
        "credential exfiltration via network",
    ),
    # Inline dangerous Python execution
    (
        re.compile(
            r"python[23]?\s+-c\s+['\"].*\b(os\.system|subprocess|shutil\.rmtree)\b",
            re.I,
        ),
        "inline dangerous Python execution",
    ),
    # Crontab manipulation
    (re.compile(r"\bcrontab\s+-[re]\b", re.I), "crontab manipulation"),
)


class CommandSanitizer:
    """Validates shell commands against security rules.

    Separated from ExecTool to allow independent testing, reuse across
    tools, and per-environment configuration.
    """

    def __init__(
        self,
        *,
        deny_patterns: tuple[tuple[re.Pattern[str], str], ...] = _DEFAULT_DENY_PATTERNS,
        extra_deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        workspace: Path | None = None,
    ) -> None:
        self._deny = list(deny_patterns)
        # Append user-configured extra patterns.
        for raw in extra_deny_patterns or []:
            self._deny.append((re.compile(raw, re.I), f"custom rule: {raw}"))
        self._allow = [re.compile(p) for p in (allow_patterns or [])]
        self._restrict = restrict_to_workspace
        self._workspace = workspace

    def check(self, command: str, cwd: str) -> SanitizeResult:
        """Check whether a command is safe to execute."""
        cmd = command.strip()
        lower = cmd.lower()

        for pattern, reason in self._deny:
            if pattern.search(lower):
                return SanitizeResult(
                    allowed=False,
                    reason=f"Command blocked by safety guard ({reason})",
                )

        if self._allow and not any(p.search(lower) for p in self._allow):
            return SanitizeResult(
                allowed=False,
                reason="Command blocked by safety guard (not in allowlist)",
            )

        if self._restrict:
            path_result = self._check_path_restriction(cmd, cwd)
            if path_result is not None:
                return path_result

        return SanitizeResult(allowed=True)

    def _check_path_restriction(self, cmd: str, cwd: str) -> SanitizeResult | None:
        """Check path traversal and workspace boundary escapes."""
        if "..\\" in cmd or "../" in cmd:
            return SanitizeResult(
                allowed=False,
                reason="Command blocked by safety guard (path traversal detected)",
            )

        cwd_path = Path(cwd).resolve()
        workspace_path = self._workspace.resolve() if self._workspace else cwd_path

        win_paths = re.findall(r"[A-Za-z]:\\[^\\\"\'\s]+", cmd)
        posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)

        for raw in win_paths + posix_paths:
            try:
                p = Path(raw.strip()).resolve()
            except Exception:
                continue
            if p.is_absolute() and workspace_path not in p.parents and p != workspace_path:
                return SanitizeResult(
                    allowed=False,
                    reason="Command blocked by safety guard (path outside workspace)",
                )
        return None
