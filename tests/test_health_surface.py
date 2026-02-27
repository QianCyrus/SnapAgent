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
