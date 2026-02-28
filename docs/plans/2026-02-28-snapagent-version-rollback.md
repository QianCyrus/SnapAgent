# SnapAgent Version Rollback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add release-channel based version rollback (canary/stable) so users can switch to older SnapAgent versions without git checkout.

**Architecture:** Keep artifacts immutable (`vX.Y.Z`, `sha-*`, `canary-*`) and expose movable channels (`stable`, `latest`, optional `canary`). Unify runtime version retrieval from package metadata, introduce release workflow for canary/tag promotion, and switch compose default to image tag selection.

**Tech Stack:** GitHub Actions, Docker/GHCR, Python packaging (`pyproject.toml` + `importlib.metadata`), Typer CLI, pytest.

---

### Task 1: Add failing tests for version source behavior

**Files:**
- Create: `tests/test_version_metadata.py`
- Test: `tests/test_version_metadata.py`

**Step 1: Write the failing test**

```python
import importlib
import importlib.metadata

import snapagent


def test_version_matches_package_metadata():
    assert snapagent.__version__ == importlib.metadata.version("snapagent-ai")


def test_version_fallback_when_metadata_missing(monkeypatch):
    import snapagent as snapagent_module

    def _raise(_: str):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    reloaded = importlib.reload(snapagent_module)
    assert reloaded.__version__ == "0.0.0+local"
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_version_metadata.py -q`
Expected: FAIL because current `snapagent.__version__` is a hardcoded literal and has no metadata fallback path.

**Step 3: Write minimal implementation**

Implement metadata-based version loading in `snapagent/__init__.py` with fallback.

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_version_metadata.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_version_metadata.py snapagent/__init__.py
git commit -m "feat: load package version from metadata with fallback"
```

### Task 2: Add release workflow for canary and stable promotion

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml` (only if needed to avoid duplicate logic)

**Step 1: Write the failing test/check**

Use workflow lint as contract:

```bash
python -m yaml  # placeholder check is not enough
```

Practical failing check: run `act` or syntax parse if available; otherwise create deterministic static checks by validating YAML keys in pytest (optional).

**Step 2: Run check to verify it fails**

Run: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: initially file missing.

**Step 3: Write minimal implementation**

Create `release.yml` with:
- Trigger A: push to `release` -> test matrix + build/push GHCR `canary-<sha>`, `sha-<sha>`, `canary`
- Trigger B: push tags `v*` -> same tests + publish package + GHCR `vX.Y.Z`, `stable`, `latest`
- Enforce no `stable/latest` update on non-tag releases.

**Step 4: Run check to verify it passes**

Run: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: valid YAML load.

**Step 5: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow for canary and stable channels"
```

### Task 3: Switch compose to image tag selection (rollback-friendly)

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Write the failing test/check**

Add/adjust shell test to assert compose includes image tag variable for gateway.

```bash
grep -n "SNAPAGENT_TAG" docker-compose.yml
```

**Step 2: Run check to verify it fails**

Run: `grep -n "SNAPAGENT_TAG" docker-compose.yml`
Expected: no match in current file.

**Step 3: Write minimal implementation**

- For `snapagent-gateway`, use image by default: `ghcr.io/<owner>/snapagent:${SNAPAGENT_TAG:-stable}`
- Keep dev build path via `profiles: [build]` service to preserve local development behavior.

**Step 4: Run check to verify it passes**

Run: `grep -n "SNAPAGENT_TAG" docker-compose.yml`
Expected: match found; compose still valid.

**Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: make compose deployments switchable by SNAPAGENT_TAG"
```

### Task 4: Document upgrade and rollback commands

**Files:**
- Modify: `README.md`

**Step 1: Write the failing test/check**

```bash
grep -n "Rollback\|回滚\|SNAPAGENT_TAG" README.md
```

**Step 2: Run check to verify it fails**

Run: `grep -n "SNAPAGENT_TAG" README.md`
Expected: no rollback section today.

**Step 3: Write minimal implementation**

Add section with copy-paste commands:
- pip fixed version install
- docker tag-based switch
- `snapagent --version` verification

**Step 4: Run check to verify it passes**

Run: `grep -n "SNAPAGENT_TAG" README.md`
Expected: rollback guidance present.

**Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add upgrade and rollback guide"
```

### Task 5: Full verification before completion

**Files:**
- Verify: repository-wide

**Step 1: Run focused tests**

Run: `.venv/bin/pytest tests/test_version_metadata.py -q`
Expected: PASS.

**Step 2: Run CI-equivalent checks**

Run:
```bash
.venv/bin/ruff check .
.venv/bin/pytest tests/ --ignore=tests/test_matrix_channel.py -q
```
Expected: PASS.

**Step 3: Sanity-check version command**

Run: `.venv/bin/snapagent --version`
Expected: prints SnapAgent and package version string.

**Step 4: Review final diff**

Run: `git status --short && git diff --stat`
Expected: only planned files changed.

**Step 5: Commit final integration if needed**

```bash
git add -A
git commit -m "feat: add release-channel rollback support"
```

