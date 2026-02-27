from __future__ import annotations

import pytest

from snapagent.agent.tools.web import WebSearchTool


class _FakeResponse:
    def __init__(self, *, text: str = "", json_data: dict | None = None) -> None:
        self.text = text
        self._json_data = json_data or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._json_data


@pytest.mark.asyncio
async def test_web_search_uses_brave_key_in_request_header(monkeypatch):
    seen_headers: dict[str, str] = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url, *, params=None, headers=None, timeout=None):
            seen_headers.update(headers or {})
            return _FakeResponse(
                json_data={
                    "web": {
                        "results": [
                            {
                                "title": "Example",
                                "url": "https://example.com",
                                "description": "Example description",
                            }
                        ]
                    }
                }
            )

    monkeypatch.setattr("snapagent.agent.tools.web.httpx.AsyncClient", _FakeClient)
    tool = WebSearchTool(api_key="brave-test-key")

    result = await tool.execute("example query")

    assert seen_headers.get("X-Subscription-Token") == "brave-test-key"
    assert "Results for: example query" in result
    assert "https://example.com" in result


@pytest.mark.asyncio
async def test_web_search_fallback_works_without_brave_key(monkeypatch):
    html_doc = """
    <html><body>
      <a class="result__a" href="https://example.org">Example Org</a>
      <div class="result__snippet">Example snippet text.</div>
    </body></html>
    """

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, _url, *, params=None, headers=None, timeout=None):
            return _FakeResponse(text=html_doc)

    monkeypatch.setattr("snapagent.agent.tools.web.httpx.AsyncClient", _FakeClient)
    tool = WebSearchTool(api_key=None)

    result = await tool.execute("fallback query")

    assert "Results for: fallback query" in result
    assert "Example Org" in result
    assert "https://example.org" in result
