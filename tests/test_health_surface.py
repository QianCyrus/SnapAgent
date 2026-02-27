"""Tests for Health surface snapshot and CLI contract."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from snapagent.cli.commands import app
from snapagent.config.schema import Config
from snapagent.observability.health import collect_health_snapshot

runner = CliRunner()


def _build_config(tmp_path, *, with_provider_key: bool) -> tuple[Config, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    config = Config()
    config.agents.defaults.workspace = str(workspace)
    config.agents.defaults.provider = "openrouter"
    config.agents.defaults.model = "openrouter/anthropic/claude-opus-4-5"

    if with_provider_key:
        config.providers.openrouter.api_key = "test-key"
    else:
        config.providers.openrouter.api_key = ""

    return config, str(workspace)


def test_collect_health_snapshot_ok(tmp_path):
    config, _ = _build_config(tmp_path, with_provider_key=True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    snapshot = collect_health_snapshot(config=config, config_path=config_path)

    assert snapshot.liveness == "ok"
    assert snapshot.readiness == "ok"
    provider = next(e for e in snapshot.evidence if e.component == "provider")
    assert provider.status == "ok"


def test_collect_health_snapshot_dependency_down(tmp_path):
    config, _ = _build_config(tmp_path, with_provider_key=False)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    snapshot = collect_health_snapshot(config=config, config_path=config_path)

    assert snapshot.readiness == "failed"
    provider = next(e for e in snapshot.evidence if e.component == "provider")
    assert provider.status == "failed"


def test_collect_health_snapshot_accepts_anthropic_auth_token_env(tmp_path, monkeypatch):
    config, _ = _build_config(tmp_path, with_provider_key=False)
    config.agents.defaults.provider = "anthropic"
    config.agents.defaults.model = "claude-opus-4-5"
    config.providers.anthropic.api_key = ""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SNAPAGENT_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "auth-token")

    snapshot = collect_health_snapshot(config=config, config_path=config_path)

    provider = next(e for e in snapshot.evidence if e.component == "provider")
    assert provider.status == "ok"


def test_collect_health_snapshot_accepts_custom_openai_api_key_env(tmp_path, monkeypatch):
    config, _ = _build_config(tmp_path, with_provider_key=False)
    config.agents.defaults.provider = "custom"
    config.agents.defaults.model = "gpt-4o-mini"
    config.providers.custom.api_key = ""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.delenv("SNAPAGENT_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-custom-openai")

    snapshot = collect_health_snapshot(config=config, config_path=config_path)

    provider = next(e for e in snapshot.evidence if e.component == "provider")
    assert provider.status == "ok"


def test_collect_health_snapshot_vllm_requires_auth(tmp_path, monkeypatch):
    config, _ = _build_config(tmp_path, with_provider_key=False)
    config.agents.defaults.provider = "vllm"
    config.agents.defaults.model = "vllm/meta-llama-3.1-8b-instruct"
    config.providers.vllm.api_base = "http://localhost:8000/v1"
    config.providers.vllm.api_key = ""
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.delenv("HOSTED_VLLM_API_KEY", raising=False)
    monkeypatch.delenv("SNAPAGENT_API_KEY", raising=False)

    snapshot = collect_health_snapshot(config=config, config_path=config_path)

    provider = next(e for e in snapshot.evidence if e.component == "provider")
    assert provider.status == "failed"
    assert provider.details["has_auth"] is False


def test_collect_health_snapshot_degraded_with_queue_backlog(tmp_path):
    config, _ = _build_config(tmp_path, with_provider_key=True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    class _BackloggedBus:
        inbound_size = 60
        outbound_size = 3

    snapshot = collect_health_snapshot(config=config, config_path=config_path, bus=_BackloggedBus())

    assert snapshot.readiness == "degraded"
    assert snapshot.degraded is True
    runtime_queue = next(e for e in snapshot.evidence if e.component == "runtime.queue")
    assert runtime_queue.status == "degraded"


def test_health_command_json_output(tmp_path, monkeypatch):
    config, _ = _build_config(tmp_path, with_provider_key=True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("snapagent.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("snapagent.config.loader.load_config", lambda: config)

    result = runner.invoke(app, ["health", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["liveness"] == "ok"
    assert payload["readiness"] == "ok"
    assert isinstance(payload["evidence"], list)


def test_status_deep_json_output_contains_details(tmp_path, monkeypatch):
    config, _ = _build_config(tmp_path, with_provider_key=True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("snapagent.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("snapagent.config.loader.load_config", lambda: config)

    result = runner.invoke(app, ["status", "--deep", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    provider = next(e for e in payload["evidence"] if e["component"] == "provider")
    assert "details" in provider


def test_status_deep_json_output_degraded_contract(tmp_path, monkeypatch):
    config, _ = _build_config(tmp_path, with_provider_key=True)
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("snapagent.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("snapagent.config.loader.load_config", lambda: config)

    from snapagent.observability import health as health_mod

    real_collect = health_mod.collect_health_snapshot

    def _collect_with_backlog(*, config, config_path, bus=None):
        class _BackloggedBus:
            inbound_size = 80
            outbound_size = 5

        return real_collect(config=config, config_path=config_path, bus=_BackloggedBus())

    monkeypatch.setattr("snapagent.observability.health.collect_health_snapshot", _collect_with_backlog)

    result = runner.invoke(app, ["status", "--deep", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["readiness"] == "degraded"
    assert payload["degraded"] is True
    runtime_queue = next(e for e in payload["evidence"] if e["component"] == "runtime.queue")
    assert runtime_queue["status"] == "degraded"
    assert runtime_queue["details"]["inbound_size"] == 80
