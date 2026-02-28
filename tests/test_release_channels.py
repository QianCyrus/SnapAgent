import tomllib
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
    assert "github.event.created" in runs
    assert "github.event.forced" in runs


def test_stable_docker_publish_waits_for_pypi_publish():
    workflow = _load_yaml(".github/workflows/release.yml")
    canary_job = workflow["jobs"]["docker_canary"]
    stable_job = workflow["jobs"]["docker_stable"]

    assert canary_job["if"] == "github.ref == 'refs/heads/release'"
    assert stable_job["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert set(stable_job["needs"]) >= {"quality", "guard_tag", "pypi"}


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


def test_release_publish_jobs_are_gated_by_quality_workflow():
    workflow = _load_yaml(".github/workflows/release.yml")
    jobs = workflow["jobs"]

    assert "quality" in jobs
    assert jobs["quality"]["uses"] == "./.github/workflows/quality.yml"
    assert "quality" in jobs["guard_tag"]["needs"]
    assert "quality" in jobs["pypi"]["needs"]
    assert "quality" in jobs["docker_canary"]["needs"]
    assert "quality" in jobs["docker_stable"]["needs"]


def test_canary_channel_has_concurrency_control():
    workflow = _load_yaml(".github/workflows/release.yml")
    canary_job = workflow["jobs"]["docker_canary"]

    assert canary_job["concurrency"]["group"] == "release-canary-channel"
    assert canary_job["concurrency"]["cancel-in-progress"] is True


def test_stable_channel_has_concurrency_and_latest_tag_gate():
    workflow = _load_yaml(".github/workflows/release.yml")
    stable_job = workflow["jobs"]["docker_stable"]

    assert stable_job["concurrency"]["group"] == "release-stable-channel"
    assert stable_job["concurrency"]["cancel-in-progress"] is False

    runs = "\n".join(
        str(step.get("run", ""))
        for step in stable_job["steps"]
        if isinstance(step, dict)
    )
    assert "git tag --merged origin/release --list 'v*' | sort -V | tail -n 1" in runs
    assert "promote_channel=true" in runs
    assert "promote_channel=false" in runs
    assert 'if [[ "${promote_channel}" == "true" ]]; then' in runs


def test_dev_dependencies_include_yaml_parser():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_deps = pyproject["project"]["optional-dependencies"]["dev"]

    assert any(dep.lower().startswith("pyyaml") for dep in dev_deps)


def test_ci_workflow_reuses_quality_workflow():
    ci_workflow = _load_yaml(".github/workflows/ci.yml")
    ci_jobs = ci_workflow["jobs"]

    assert "quality" in ci_jobs
    assert ci_jobs["quality"]["uses"] == "./.github/workflows/quality.yml"


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
