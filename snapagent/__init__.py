"""SnapAgent - A lightweight AI agent framework."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("snapagent-ai")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
__logo__ = "🐈"
__app_name__ = "SnapAgent"
