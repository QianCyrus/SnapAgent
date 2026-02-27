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


@pytest.mark.asyncio
async def test_web_search_passes_freshness_and_language_to_brave(monkeypatch):
    seen_params: dict[str, str] = {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, headers=None, timeout=None):
            if "api.search.brave.com" in url:
                seen_params.update(params or {})
                return _FakeResponse(
                    json_data={
                        "web": {
                            "results": [
                                {
                                    "title": f"Result {i}",
                                    "url": f"https://example.com/{i}",
                                    "description": "desc",
                                }
                                for i in range(10)
                            ]
                        }
                    }
                )
            return _FakeResponse(text="")

    monkeypatch.setattr("snapagent.agent.tools.web.httpx.AsyncClient", _FakeClient)
    tool = WebSearchTool(api_key="brave-test-key")

    _ = await tool.execute("openai api", freshness="week", language="zh-CN")

    assert seen_params.get("freshness") == "pw"
    assert seen_params.get("search_lang") == "zh-CN"


@pytest.mark.asyncio
async def test_web_search_fallback_uses_duckduckgo_lite_when_html_is_empty(monkeypatch):
    lite_doc = """
    <html><body>
      <table>
        <tr><td><a href="https://lite.example.com/doc">Lite Result</a></td></tr>
        <tr><td>Lite snippet text.</td></tr>
      </table>
    </body></html>
    """

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, headers=None, timeout=None):
            if "duckduckgo.com/html/" in url:
                return _FakeResponse(text="<html><body>No matches</body></html>")
            if "lite.duckduckgo.com/lite/" in url:
                return _FakeResponse(text=lite_doc)
            return _FakeResponse(text="")

    monkeypatch.setattr("snapagent.agent.tools.web.httpx.AsyncClient", _FakeClient)
    tool = WebSearchTool(api_key=None)

    result = await tool.execute("lite fallback")

    assert "Results for: lite fallback" in result
    assert "Lite Result" in result
    assert "https://lite.example.com/doc" in result


def test_web_search_merge_and_rank_dedupes_equivalent_urls() -> None:
    query = "openai api"
    merged = WebSearchTool._merge_and_rank(
        query,
        [
            {
                "title": "Generic",
                "url": "https://example.com/article?utm_source=ads",
                "description": "",
            },
            {
                "title": "OpenAI API Guide",
                "url": "https://example.com/article",
                "description": "best match",
            },
            {
                "title": "Other docs",
                "url": "https://other.com/doc",
                "description": "api reference",
            },
        ],
    )

    assert len(merged) == 2
    assert merged[0]["url"] == "https://example.com/article"
    assert merged[0]["title"] == "OpenAI API Guide"
