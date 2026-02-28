import importlib
import importlib.metadata


def test_version_matches_package_metadata():
    import snapagent

    assert snapagent.__version__ == importlib.metadata.version("snapagent-ai")


def test_version_fallback_when_metadata_missing(monkeypatch):
    import snapagent

    original_version = importlib.metadata.version

    def _patched_version(name: str) -> str:
        if name == "snapagent-ai":
            raise importlib.metadata.PackageNotFoundError
        return original_version(name)

    monkeypatch.setattr(importlib.metadata, "version", _patched_version)

    reloaded = importlib.reload(snapagent)
    try:
        assert reloaded.__version__ == "0.0.0+local"
    finally:
        importlib.reload(reloaded)
