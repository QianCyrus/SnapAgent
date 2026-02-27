import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from snapagent.cli.commands import app
from snapagent.config.schema import Config
from snapagent.interfaces.config_migration import migrate_config_dict_v1_to_v2
from snapagent.providers.litellm_provider import LiteLLMProvider
from snapagent.providers.openai_codex_provider import _strip_model_prefix
from snapagent.providers.registry import find_by_model

runner = CliRunner()


@pytest.fixture
def mock_paths():
    """Mock config/workspace paths for test isolation."""
    with (
        patch("snapagent.config.loader.get_config_path") as mock_cp,
        patch("snapagent.config.loader.save_config") as mock_sc,
        patch("snapagent.config.loader.load_config"),
        patch("snapagent.utils.helpers.get_workspace_path") as mock_ws,
    ):
        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_sc.side_effect = lambda config: config_file.write_text("{}")

        yield config_file, workspace_dir

        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """No existing config — should create from scratch."""
    config_file, workspace_dir = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "SnapAgent is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()


def test_onboard_existing_config_refresh(mock_paths):
    """Config exists, user declines overwrite — should refresh (load-merge-save)."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """Config exists, user confirms overwrite — should reset to defaults."""
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """Workspace exists — should not recreate, but still add missing templates."""
    config_file, workspace_dir = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout
    assert "Created AGENTS.md" in result.stdout
    assert (workspace_dir / "AGENTS.md").exists()


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_config_matches_volcengine_for_doubao_seed_with_env_only_key(monkeypatch):
    config = Config()
    config.agents.defaults.model = "doubao-seed-1-8-251228"
    config.providers.volcengine.api_key = ""
    monkeypatch.setenv("OPENAI_API_KEY", "seed-test-key")

    assert config.get_provider_name() == "volcengine"


def test_config_doubao_seed_without_auth_does_not_match_provider(monkeypatch):
    config = Config()
    config.agents.defaults.model = "doubao-seed-1-8-251228"
    config.providers.volcengine.api_key = ""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SNAPAGENT_API_KEY", raising=False)

    assert config.get_provider_name() is None


def test_find_by_model_prefers_explicit_prefix_over_generic_codex_keyword():
    spec = find_by_model("github-copilot/gpt-5.3-codex")

    assert spec is not None
    assert spec.name == "github_copilot"


def test_litellm_provider_canonicalizes_github_copilot_hyphen_prefix():
    provider = LiteLLMProvider(default_model="github-copilot/gpt-5.3-codex")

    resolved = provider._resolve_model("github-copilot/gpt-5.3-codex")

    assert resolved == "github_copilot/gpt-5.3-codex"


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


def test_config_migration_adds_compression_and_version():
    source = {
        "tools": {"exec": {"timeout": 30, "restrictToWorkspace": True}},
    }
    migrated = migrate_config_dict_v1_to_v2(source)

    assert migrated["config_version"] == "v2"
    assert "compression" in migrated
    assert migrated["tools"]["restrictToWorkspace"] is True
    assert "restrictToWorkspace" not in migrated["tools"]["exec"]


def test_config_migration_is_idempotent():
    v2 = migrate_config_dict_v1_to_v2({"config_version": "v2", "compression": {"mode": "balanced"}})
    rerun = migrate_config_dict_v1_to_v2(v2)
    assert rerun == v2


def test_migrate_config_command_writes_v2_and_backup(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": {"exec": {"restrictToWorkspace": True}}}))

    monkeypatch.setattr("snapagent.config.loader.get_config_path", lambda: config_path)

    result = runner.invoke(app, ["migrate-config", "--from", "v1", "--to", "v2"])

    assert result.exit_code == 0
    data = json.loads(config_path.read_text())
    assert data["config_version"] == "v2"
    assert "compression" in data
    assert (tmp_path / "config.json.bak").exists()


def test_status_shows_web_search_fallback_when_no_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")

    monkeypatch.setattr("snapagent.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("snapagent.config.loader.load_config", lambda: Config())
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "SnapAgent Status" in result.stdout
    assert "Web Search: fallback mode" in result.stdout
