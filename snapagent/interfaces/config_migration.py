"""Config migration helpers for compatibility between schema versions."""

from __future__ import annotations

from copy import deepcopy


def migrate_config_dict_v1_to_v2(data: dict) -> dict:
    """Migrate a v1-style config dict to v2 (idempotent)."""
    out = deepcopy(data)

    # Normalize legacy top-level alias if present.
    if "configVersion" in out and "config_version" not in out:
        out["config_version"] = out.pop("configVersion")

    tools = out.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
        out["tools"] = tools

    if "compression" not in out:
        out["compression"] = {
            "enabled": True,
            "mode": "balanced",
            "tokenBudgetRatio": 0.65,
            "recencyTurns": 6,
            "salienceThreshold": 0.7,
            "maxFacts": 12,
            "maxSummaryChars": 1400,
        }

    out["config_version"] = "v2"
    return out
