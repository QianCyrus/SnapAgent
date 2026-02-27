"""Health surface aggregation for SnapAgent observability."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from snapagent.config.schema import Config
from snapagent.providers.registry import find_by_name

_CHANNEL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "whatsapp": ("bridge_url",),
    "telegram": ("token",),
    "discord": ("token",),
    "feishu": ("app_id", "app_secret"),
    "mochat": ("claw_token",),
    "dingtalk": ("client_id", "client_secret"),
    "email": ("imap_host", "imap_username", "imap_password"),
    "slack": ("bot_token", "app_token"),
    "qq": ("app_id", "secret"),
    "matrix": ("homeserver", "access_token", "user_id"),
}

_CRITICAL_COMPONENTS = {"config", "workspace", "provider"}
_STATUS_ORDER = {"ok": 0, "unknown": 1, "degraded": 2, "failed": 3}


def _worst(a: str, b: str) -> str:
    return a if _STATUS_ORDER.get(a, 99) >= _STATUS_ORDER.get(b, 99) else b


@dataclass(slots=True)
class HealthEvidence:
    """Component-level health status with optional machine details."""

    component: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, deep: bool = False) -> dict[str, Any]:
        payload = {
            "component": self.component,
            "status": self.status,
            "summary": self.summary,
        }
        if deep:
            payload["details"] = self.details
        return payload


@dataclass(slots=True)
class HealthSnapshot:
    """Top-level health snapshot exposed by the Health surface."""

    liveness: str
    readiness: str
    degraded: bool
    generated_at: str
    evidence: list[HealthEvidence] = field(default_factory=list)

    def to_dict(self, *, deep: bool = False) -> dict[str, Any]:
        return {
            "liveness": self.liveness,
            "readiness": self.readiness,
            "degraded": self.degraded,
            "generated_at": self.generated_at,
            "evidence": [item.to_dict(deep=deep) for item in self.evidence],
        }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _provider_evidence(config: Config) -> HealthEvidence:
    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    details: dict[str, Any] = {"model": model, "provider": provider_name}

    if not provider_name:
        return HealthEvidence(
            component="provider",
            status="failed",
            summary="No provider matched for current model/auth settings",
            details=details,
        )

    spec = find_by_name(provider_name)
    provider_cfg = getattr(config.providers, provider_name, None)
    details["provider_kind"] = (
        "oauth"
        if spec and spec.is_oauth
        else "local"
        if spec and spec.is_local
        else "api_key"
    )

    if spec and spec.is_oauth:
        return HealthEvidence(
            component="provider",
            status="ok",
            summary=f"OAuth provider selected: {provider_name}",
            details=details,
        )

    if spec and spec.is_local:
        api_base = provider_cfg.api_base if provider_cfg else None
        if _has_value(api_base):
            details["api_base"] = api_base
            return HealthEvidence(
                component="provider",
                status="ok",
                summary=f"Local provider configured: {provider_name}",
                details=details,
            )
        return HealthEvidence(
            component="provider",
            status="failed",
            summary=f"Local provider missing api_base: {provider_name}",
            details=details,
        )

    has_key = bool(provider_cfg and _has_value(provider_cfg.api_key))
    env_key = spec.env_key if spec else ""
    if not has_key and env_key:
        has_key = bool(os.environ.get(env_key, "").strip())
    if not has_key:
        has_key = bool(os.environ.get("SNAPAGENT_API_KEY", "").strip())

    details["has_auth"] = has_key
    if has_key:
        return HealthEvidence(
            component="provider",
            status="ok",
            summary=f"Provider configured: {provider_name}",
            details=details,
        )

    return HealthEvidence(
        component="provider",
        status="failed",
        summary=f"Provider missing credentials: {provider_name}",
        details=details,
    )


def _channels_evidence(config: Config) -> HealthEvidence:
    channels = config.channels
    enabled: list[str] = []
    misconfigured: dict[str, list[str]] = {}

    for name, required in _CHANNEL_REQUIRED_FIELDS.items():
        ch = getattr(channels, name, None)
        if ch is None or not getattr(ch, "enabled", False):
            continue
        enabled.append(name)
        missing = [field for field in required if not _has_value(getattr(ch, field, None))]
        if name == "email" and not bool(getattr(ch, "consent_granted", False)):
            missing.append("consent_granted")
        if missing:
            misconfigured[name] = missing

    details = {
        "enabled_channels": enabled,
        "enabled_count": len(enabled),
        "misconfigured": misconfigured,
    }

    if not enabled:
        return HealthEvidence(
            component="channels",
            status="ok",
            summary="No external channels enabled",
            details=details,
        )
    if misconfigured:
        return HealthEvidence(
            component="channels",
            status="failed",
            summary="One or more enabled channels are misconfigured",
            details=details,
        )
    return HealthEvidence(
        component="channels",
        status="ok",
        summary=f"{len(enabled)} enabled channel(s) configured",
        details=details,
    )


def _runtime_queue_evidence(bus: Any | None) -> HealthEvidence:
    if bus is None:
        return HealthEvidence(
            component="runtime.queue",
            status="unknown",
            summary="Runtime queue metrics unavailable in CLI-only context",
            details={},
        )

    inbound = int(getattr(bus, "inbound_size", 0))
    outbound = int(getattr(bus, "outbound_size", 0))
    peak = max(inbound, outbound)
    status = "ok"
    if peak >= 200:
        status = "failed"
    elif peak >= 50:
        status = "degraded"

    return HealthEvidence(
        component="runtime.queue",
        status=status,
        summary=f"Queue sizes inbound={inbound}, outbound={outbound}",
        details={"inbound_size": inbound, "outbound_size": outbound},
    )


def collect_health_snapshot(
    *,
    config: Config,
    config_path: Path,
    bus: Any | None = None,
) -> HealthSnapshot:
    """Collect a machine-readable health snapshot with component evidence."""
    evidence: list[HealthEvidence] = []

    config_exists = config_path.exists()
    evidence.append(
        HealthEvidence(
            component="config",
            status="ok" if config_exists else "failed",
            summary="Config file found" if config_exists else "Config file not found",
            details={"path": str(config_path)},
        )
    )

    workspace = config.workspace_path
    workspace_exists = workspace.exists()
    evidence.append(
        HealthEvidence(
            component="workspace",
            status="ok" if workspace_exists else "failed",
            summary="Workspace exists" if workspace_exists else "Workspace missing",
            details={"path": str(workspace)},
        )
    )

    evidence.append(_provider_evidence(config))
    evidence.append(_channels_evidence(config))
    evidence.append(_runtime_queue_evidence(bus))

    liveness = "ok"
    for item in evidence:
        if item.component in {"config", "workspace"}:
            liveness = _worst(liveness, item.status)

    readiness = "ok"
    for item in evidence:
        if item.component in _CRITICAL_COMPONENTS:
            readiness = _worst(readiness, item.status)
    if readiness == "ok":
        for item in evidence:
            if item.status in {"degraded", "failed"}:
                readiness = item.status
                break

    return HealthSnapshot(
        liveness=liveness,
        readiness=readiness,
        degraded=any(item.status == "degraded" for item in evidence),
        generated_at=datetime.now(timezone.utc).isoformat(),
        evidence=evidence,
    )

