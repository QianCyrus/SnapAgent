"""Web tools: web_search and web_fetch."""

import html
import json
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import httpx

from snapagent.agent.tools.base import Tool

# Shared constants
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # Limit redirects to prevent DoS attacks


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """Normalize whitespace."""
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """Validate URL: must be http(s) with valid domain."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebSearchTool(Tool):
    """Search the web using Brave Search API."""

    name = "web_search"
    description = "Search the web. Returns titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {
                "type": "integer",
                "description": "Results (1-10)",
                "minimum": 1,
                "maximum": 10,
            },
            "freshness": {
                "type": "string",
                "description": "Optional freshness filter: day/week/month/year",
                "enum": ["day", "week", "month", "year"],
            },
            "language": {
                "type": "string",
                "description": "Optional language hint (e.g. en, zh-CN)",
            },
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._init_api_key = api_key
        self.max_results = max_results

    @property
    def api_key(self) -> str:
        """Resolve API key at call time so env/config changes are picked up."""
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(
        self,
        query: str,
        count: int | None = None,
        freshness: str | None = None,
        language: str | None = None,
        **kwargs: Any,
    ) -> str:
        # Backward-compatible handling for camelCase arguments from tool calls.
        if "freshness" in kwargs and freshness is None:
            freshness = kwargs["freshness"]
        if "language" in kwargs and language is None:
            language = kwargs["language"]

        n = min(max(count or self.max_results, 1), 10)
        fetch_n = min(10, max(n * 2, n))
        query_variants = self._query_variants(query)
        language = (language or "").strip() or self._default_language(query)
        brave_error: str | None = None
        merged: list[dict[str, Any]] = []

        if self.api_key:
            try:
                for q in query_variants:
                    brave_results = await self._search_brave(
                        q, fetch_n, freshness=freshness, language=language
                    )
                    merged = self._merge_and_rank(query, merged + brave_results)
                    if len(merged) >= n:
                        break
            except Exception as e:
                brave_error = str(e)

        fallback_error: str | None = None
        if len(merged) < n:
            try:
                ddg_results: list[dict[str, Any]] = []
                for q in query_variants:
                    ddg_results.extend(await self._search_duckduckgo(q, fetch_n, language=language))
                    if len(ddg_results) >= n:
                        break
                merged = self._merge_and_rank(query, merged + ddg_results)
            except Exception as e:
                fallback_error = str(e)

        if merged:
            result = self._format_search_results(query, merged, n)
            if brave_error and self.api_key:
                return f"[Web search degraded] Brave Search unavailable: {brave_error}\n\n{result}"
            return result

        if brave_error and fallback_error:
            return f"Error: Web search failed (Brave + fallback): {fallback_error}"
        return (
            "Error: Web search fallback failed and Brave Search API key is not configured. "
            "Set tools.web.search.apiKey in ~/.snapagent/config.json (or export BRAVE_API_KEY)."
        )

    async def _search_brave(
        self,
        query: str,
        count: int,
        *,
        freshness: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": query, "count": count}
        if freshness in {"day", "week", "month", "year"}:
            params["freshness"] = self._map_freshness(freshness)
        if language:
            params["search_lang"] = language

        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                timeout=10.0,
            )
            r.raise_for_status()

        raw = r.json().get("web", {}).get("results", [])
        results: list[dict[str, Any]] = []
        for item in raw:
            url = self._normalize_result_url(item.get("url", ""))
            if not url:
                continue
            results.append(
                {
                    "title": _normalize(_strip_tags(str(item.get("title", "")))),
                    "url": url,
                    "description": _normalize(_strip_tags(str(item.get("description", "")))),
                    "_source": "brave",
                }
            )
        return results

    async def _search_duckduckgo(
        self, query: str, count: int, *, language: str | None = None
    ) -> list[dict[str, Any]]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": self._accept_language(language),
        }

        # Extensible backend pipeline: append new sources here without changing caller logic.
        backends = (
            self._search_duckduckgo_html_backend,
            self._search_duckduckgo_lite_backend,
        )
        for backend in backends:
            try:
                results = await backend(query, count, headers)
            except Exception:
                continue
            if results:
                return results
        return []

    async def _search_duckduckgo_html_backend(
        self, query: str, count: int, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                headers=headers,
                timeout=15.0,
            )
            r.raise_for_status()
            return self._parse_duckduckgo_html(r.text, count)

    async def _search_duckduckgo_lite_backend(
        self, query: str, count: int, headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers=headers,
                timeout=15.0,
            )
            r.raise_for_status()
            return self._parse_duckduckgo_lite(r.text, count)

    @staticmethod
    def _unwrap_duckduckgo_url(url: str) -> str:
        parsed = urlparse(url)
        if "duckduckgo.com" not in parsed.netloc or not parsed.path.startswith("/l/"):
            return url
        target = parse_qs(parsed.query).get("uddg", [])
        return unquote(target[0]) if target else url

    @staticmethod
    def _normalize_result_url(url: str) -> str:
        try:
            parsed = urlparse(url.strip())
        except Exception:
            return ""
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        path = parsed.path or "/"
        path = re.sub(r"/{2,}", "/", path)
        query_pairs = []
        if parsed.query:
            for part in parsed.query.split("&"):
                if not part:
                    continue
                key = part.split("=", 1)[0].lower()
                if key.startswith("utm_") or key in {"fbclid", "gclid", "ref", "source"}:
                    continue
                query_pairs.append(part)
        query = "&".join(sorted(query_pairs))
        return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", query, ""))

    @staticmethod
    def _map_freshness(value: str) -> str:
        mapping = {
            "day": "pd",
            "week": "pw",
            "month": "pm",
            "year": "py",
        }
        return mapping.get(value, "")

    @staticmethod
    def _default_language(query: str) -> str:
        if re.search(r"[\u4e00-\u9fff]", query):
            return "zh-hans"
        return "en"

    @staticmethod
    def _accept_language(language: str | None) -> str:
        code = (language or "").strip().lower()
        if code.startswith("zh"):
            return "zh-CN,zh;q=0.9,en;q=0.7"
        return "en-US,en;q=0.9"

    @staticmethod
    def _query_variants(query: str) -> list[str]:
        base = " ".join(query.strip().split())
        if not base:
            return []
        variants = [base]
        # Relax quoted queries if strict matching returns sparse results.
        if (base.startswith('"') and base.endswith('"')) or (base.startswith("'") and base.endswith("'")):
            relaxed = base[1:-1].strip()
            if relaxed:
                variants.append(relaxed)
        if re.search(r"[\u4e00-\u9fff]", base):
            no_space = base.replace(" ", "")
            if no_space and no_space != base:
                variants.append(no_space)
        deduped: list[str] = []
        seen: set[str] = set()
        for q in variants:
            if q.lower() not in seen:
                seen.add(q.lower())
                deduped.append(q)
        return deduped

    @staticmethod
    def _parse_duckduckgo_html(html_body: str, count: int) -> list[dict[str, Any]]:
        links = re.findall(
            r"<a[^>]*class=['\"][^'\"]*result__a[^'\"]*['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            html_body,
            flags=re.I | re.S,
        )
        snippets = re.findall(
            r"<[^>]*class=['\"][^'\"]*result__snippet[^'\"]*['\"][^>]*>(.*?)</[^>]+>",
            html_body,
            flags=re.I | re.S,
        )
        results: list[dict[str, Any]] = []
        for i, (href, title_html) in enumerate(links[:count]):
            url = WebSearchTool._normalize_result_url(WebSearchTool._unwrap_duckduckgo_url(href))
            if not url:
                continue
            desc = _strip_tags(snippets[i]) if i < len(snippets) else ""
            results.append(
                {
                    "title": _normalize(_strip_tags(title_html)),
                    "url": url,
                    "description": _normalize(desc),
                    "_source": "duckduckgo",
                }
            )
        return results

    @staticmethod
    def _parse_duckduckgo_lite(html_body: str, count: int) -> list[dict[str, Any]]:
        pattern = re.compile(
            r"<a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>(?:[\s\S]{0,400}?<td[^>]*>(.*?)</td>)?",
            flags=re.I | re.S,
        )
        results: list[dict[str, Any]] = []
        for href, title_html, snippet_html in pattern.findall(html_body):
            if len(results) >= count:
                break
            url = WebSearchTool._normalize_result_url(WebSearchTool._unwrap_duckduckgo_url(href))
            if not url:
                continue
            title = _normalize(_strip_tags(title_html))
            if not title:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "description": _normalize(_strip_tags(snippet_html or "")),
                    "_source": "duckduckgo-lite",
                }
            )
        return results

    @staticmethod
    def _merge_and_rank(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        query_terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]
        query_text = query.lower().strip()

        dedup: dict[str, dict[str, Any]] = {}
        for idx, item in enumerate(results):
            url = WebSearchTool._normalize_result_url(str(item.get("url", "")))
            if not url:
                continue
            title = str(item.get("title", "")).strip()
            desc = str(item.get("description", "")).strip()
            blob = f"{title} {desc} {url}".lower()
            score = 0.0
            if query_text and query_text in blob:
                score += 4.0
            for term in query_terms:
                if term in title.lower():
                    score += 1.8
                elif term in desc.lower():
                    score += 0.9
                elif term in url.lower():
                    score += 0.6
            if title:
                score += 0.3
            if desc:
                score += 0.3
            score -= idx * 0.02  # Keep early result order as soft tie-breaker.

            normalized = {
                "title": title or url,
                "url": url,
                "description": desc,
                "_score": score,
                "_source": item.get("_source", "unknown"),
            }
            prev = dedup.get(url)
            if prev is None or normalized["_score"] > prev["_score"]:
                dedup[url] = normalized

        ranked = sorted(dedup.values(), key=lambda x: x.get("_score", 0.0), reverse=True)
        for item in ranked:
            item.pop("_score", None)
        return ranked

    @staticmethod
    def _format_search_results(query: str, results: list[dict[str, Any]], count: int) -> str:
        if not results:
            return f"No results for: {query}"

        lines = [f"Results for: {query}\n"]
        for i, item in enumerate(results[:count], 1):
            lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
            if desc := item.get("description"):
                lines.append(f"   {desc}")
        lines.append(
            "\nTip: Use web_fetch on the most relevant URL above to read the full page content."
        )
        return "\n".join(lines)


class WebFetchTool(Tool):
    """Fetch and extract content from a URL using Readability."""

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100},
        },
        "required": ["url"],
    }

    def __init__(self, max_chars: int = 50000):
        self.max_chars = max_chars

    async def execute(
        self,
        url: str,
        extract_mode: str = "markdown",
        max_chars: int | None = None,
        **kwargs: Any,
    ) -> str:
        from readability import Document

        # Backward-compatible handling for camelCase arguments from tool calls.
        if "extractMode" in kwargs:
            extract_mode = kwargs["extractMode"]
        if "maxChars" in kwargs:
            max_chars = kwargs["maxChars"]
        max_chars = max_chars or self.max_chars

        # Validate URL before fetching
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps(
                {"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False
            )

        try:
            async with httpx.AsyncClient(
                follow_redirects=True, max_redirects=MAX_REDIRECTS, timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            # JSON
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            # HTML
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = (
                    self._to_markdown(doc.summary())
                    if extract_mode == "markdown"
                    else _strip_tags(doc.summary())
                )
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"

            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]

            return json.dumps(
                {
                    "url": url,
                    "finalUrl": str(r.url),
                    "status": r.status_code,
                    "extractor": extractor,
                    "truncated": truncated,
                    "length": len(text),
                    "text": text,
                },
                ensure_ascii=False,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    def _to_markdown(self, html: str) -> str:
        """Convert HTML to markdown."""
        # Convert links, headings, lists before stripping tags
        text = re.sub(
            r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
            lambda m: f"[{_strip_tags(m[2])}]({m[1]})",
            html,
            flags=re.I,
        )
        text = re.sub(
            r"<h([1-6])[^>]*>([\s\S]*?)</h\1>",
            lambda m: f"\n{'#' * int(m[1])} {_strip_tags(m[2])}\n",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"<li[^>]*>([\s\S]*?)</li>", lambda m: f"\n- {_strip_tags(m[1])}", text, flags=re.I
        )
        text = re.sub(r"</(p|div|section|article)>", "\n\n", text, flags=re.I)
        text = re.sub(r"<(br|hr)\s*/?>", "\n", text, flags=re.I)
        return _normalize(_strip_tags(text))
