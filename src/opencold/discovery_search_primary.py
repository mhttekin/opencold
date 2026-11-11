from __future__ import annotations

import json
import os
import urllib.request
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from opencold.discovery_data import (
    SEARCH_TIMEOUT,
)
from opencold.discovery_search_models import SearchResult

# ---------------------------------------------------------------------------
# Unified search: Serper API (preferred) with DDG HTML fallback
# ---------------------------------------------------------------------------


def _get_serper_key() -> str | None:
    """Return the Serper API key from env or provider config."""
    key = os.environ.get("SERPER_API_KEY")
    if key:
        return key
    try:
        from opencold import config

        prov = config.get_provider("serper")
        if prov:
            return prov.get("api_key")
        return config.get_api_key("serper")
    except Exception:
        return None


def _serper_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using Serper.dev API (free tier: 2,500 queries)."""
    key = _get_serper_key()
    if not key:
        return []
    payload = json.dumps({"q": query, "num": num}).encode()
    req = urllib.request.Request(
        "https://google.serper.dev/search",
        data=payload,
        headers={
            "X-API-KEY": key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = []
        for item in data.get("organic", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("link", ""),
                    snippet=item.get("snippet", ""),
                )
            )
        return results
    except Exception:
        return []


def _ddgs_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using ddgs package (zero-auth, uses DDG internal API)."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=num))
        results: list[SearchResult] = []
        for item in raw:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    snippet=item.get("body", ""),
                    engine="ddgs",
                )
            )
        return results
    except Exception:
        return []


def _brave_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using Brave Search HTML (zero-auth fallback)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://search.brave.com/search?q={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            data = resp.read()
            enc = resp.headers.get("Content-Encoding", "")
            if enc == "gzip":
                import gzip

                data = gzip.decompress(data)
            html = data.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []
        seen: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href = tag.get("href", "")
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if "brave.com" in parsed.netloc:
                continue
            if href in seen:
                continue
            text = tag.get_text(" ", strip=True)
            if not text or len(text) < 10:
                continue
            # Brave concatenates URL display with title; extract title
            # by finding the URL slug in the text and taking what follows
            slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            if slug and slug in text:
                title = text[text.index(slug) + len(slug) :]
            else:
                title = text
            title = title.strip()
            if not title:
                continue
            seen.add(href)
            results.append(SearchResult(title=title, url=href, engine="brave"))
            if len(results) >= num:
                break
        return results
    except Exception:
        return []
