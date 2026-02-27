"""Adaptive stripping of model reasoning tags (e.g. <think>, <reasoning>)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThinkTagConfig:
    """Configuration for one family of reasoning tags."""

    open_tag: str
    close_tag: str


# Default configurations covering known reasoning-model families.
DEFAULT_TAG_CONFIGS: tuple[ThinkTagConfig, ...] = (
    ThinkTagConfig(open_tag="think", close_tag="think"),
    ThinkTagConfig(open_tag="reasoning", close_tag="reasoning"),
    ThinkTagConfig(open_tag="thought", close_tag="thought"),
    ThinkTagConfig(open_tag="inner_monologue", close_tag="inner_monologue"),
)


class ThinkTagStripper:
    """Strips model reasoning tags from LLM output.

    Handles nested tags, unclosed trailing tags, multiline content,
    and multiple tag formats across model families.
    """

    def __init__(
        self,
        tag_configs: tuple[ThinkTagConfig, ...] = DEFAULT_TAG_CONFIGS,
    ) -> None:
        self._configs = tag_configs
        # Pre-compile patterns per config:
        #   balanced: <tag>...</tag>
        #   unclosed: <tag>... (trailing, no close)
        #   orphan_close: </tag> without a matching open
        self._patterns: list[
            tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]
        ] = []
        for cfg in self._configs:
            esc_open = re.escape(cfg.open_tag)
            esc_close = re.escape(cfg.close_tag)
            # Match innermost pairs only (no nested open tags inside).
            # Repeated application peels layers from inside out.
            innermost = re.compile(
                rf"<{esc_open}>(?:(?!<{esc_open}>)[\s\S])*?</{esc_close}>",
                re.IGNORECASE,
            )
            unclosed = re.compile(
                rf"<{esc_open}>[\s\S]*$",
                re.IGNORECASE,
            )
            orphan_close = re.compile(
                rf"</{esc_close}>",
                re.IGNORECASE,
            )
            self._patterns.append((innermost, unclosed, orphan_close))

    def strip(self, text: str | None) -> str | None:
        """Remove all reasoning tags. Returns None if result is empty."""
        if not text:
            return None
        result = text
        for balanced_re, unclosed_re, orphan_close_re in self._patterns:
            # Repeated application handles nested balanced pairs.
            prev = None
            while prev != result:
                prev = result
                result = balanced_re.sub("", result)
            # Strip trailing unclosed tag.
            result = unclosed_re.sub("", result)
            # Strip orphaned closing tags (left over from nested stripping).
            result = orphan_close_re.sub("", result)
        stripped = result.strip()
        return stripped or None
