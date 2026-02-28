from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def test_tag_release_has_release_branch_guard():
    workflow = _load_yaml(".github/workflows/release.yml")
    guard_job = workflow["jobs"]["guard_tag"]
    assert guard_job["if"] == "startsWith(github.ref, 'refs/tags/v')"

    runs = "\n".join(
        str(step.get("run", ""))
        for step in guard_job["steps"]
        if isinstance(step, dict)
    )
    assert "merge-base --is-ancestor" in runs
    assert "origin/release" in runs


def test_stable_docker_publish_waits_for_pypi_publish():
    workflow = _load_yaml(".github/workflows/release.yml")
    canary_job = workflow["jobs"]["docker_canary"]
    stable_job = workflow["jobs"]["docker_stable"]

    assert canary_job["if"] == "github.ref == 'refs/heads/release'"
    assert stable_job["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert set(stable_job["needs"]) >= {"test", "guard_tag", "pypi"}


def test_pypi_publish_is_rerun_safe():
    workflow = _load_yaml(".github/workflows/release.yml")
    pypi_job = workflow["jobs"]["pypi"]
    runs = "\n".join(
        str(step.get("run", ""))
        for step in pypi_job["steps"]
        if isinstance(step, dict)
    )

    assert "twine upload --skip-existing dist/*" in runs


def test_ghcr_owner_is_normalized_to_lowercase():
    workflow = _load_yaml(".github/workflows/release.yml")
    canary_job = workflow["jobs"]["docker_canary"]
    stable_job = workflow["jobs"]["docker_stable"]

    canary_runs = "\n".join(
        str(step.get("run", ""))
        for step in canary_job["steps"]
        if isinstance(step, dict)
    )
    stable_runs = "\n".join(
        str(step.get("run", ""))
        for step in stable_job["steps"]
        if isinstance(step, dict)
    )

    assert "${GITHUB_REPOSITORY_OWNER,,}" in canary_runs
    assert "${GITHUB_REPOSITORY_OWNER,,}" in stable_runs


def test_compose_production_services_are_image_only():
    compose = _load_yaml("docker-compose.yml")
    services = compose["services"]

    gateway = services["snapagent-gateway"]
    cli = services["snapagent-cli"]

    assert "image" in gateway
    assert "build" not in gateway
    assert "image" in cli
    assert "build" not in cli


def test_compose_dev_services_are_build_only():
    compose = _load_yaml("docker-compose.yml")
    services = compose["services"]

    gateway_dev = services["snapagent-gateway-dev"]
    cli_dev = services["snapagent-cli-dev"]

    assert "build" in gateway_dev
    assert "image" not in gateway_dev
    assert "build" in cli_dev
    assert "image" not in cli_dev
