from __future__ import annotations

import json
import urllib.request
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from opencold.discovery_data import (
    _SEARXNG_INSTANCES,
    SEARCH_TIMEOUT,
)
from opencold.discovery_domains import (
    _clean_text,
)
from opencold.discovery_search_html import _duckduckgo_search_urls, _fetch_search_html
from opencold.discovery_search_models import SearchResult
from opencold.discovery_search_parse import _unwrap_duckduckgo_url


def _mojeek_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using Mojeek HTML (zero-auth, independent index)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.mojeek.com/search?q={encoded}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        results: list[SearchResult] = []
        # Mojeek uses <a class="ob"> or <li class="result"> patterns
        for li in soup.find_all("li", class_="result"):
            link = li.find("a", href=True, class_="ob")
            if not link:
                link = li.find("a", href=True)
            if not link:
                continue
            href = link.get("href", "")
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if "mojeek.com" in parsed.netloc:
                continue
            title = link.get_text(" ", strip=True)
            snippet_tag = li.find("p", class_="s")
            snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""
            # Mojeek sometimes shows dates in <span class="date">
            date_tag = li.find("span", class_="date")
            pub_date = date_tag.get_text(strip=True) if date_tag else ""
            if title:
                results.append(
                    SearchResult(
                        title=title,
                        url=href,
                        snippet=snippet,
                        published_date=pub_date,
                        engine="mojeek",
                    )
                )
            if len(results) >= num:
                break
        return results
    except Exception:
        return []


def _searxng_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using SearXNG public instances (JSON API, zero-auth)."""
    for instance in _SEARXNG_INSTANCES:
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"{instance}/search?q={encoded}&format=json&language=en-US"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT + 2) as resp:
                data = json.loads(resp.read().decode())
            results: list[SearchResult] = []
            for item in data.get("results", []):
                result_url = item.get("url", "")
                if not result_url:
                    continue
                # SearXNG may include publishedDate in ISO format
                pub_date = item.get("publishedDate", "")
                # Also note which engines SearXNG aggregated from
                engines = ", ".join(item.get("engines", []))
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=result_url,
                        snippet=item.get("content", ""),
                        published_date=pub_date,
                        engine=f"searxng({engines})" if engines else "searxng",
                    )
                )
                if len(results) >= num:
                    break
            if results:
                return results
        except Exception:
            continue
    return []


def _ddg_html_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using DuckDuckGo HTML scraping (last-resort fallback)."""
    results: list[SearchResult] = []
    for search_url in _duckduckgo_search_urls(query):
        html = _fetch_search_html(search_url)
        if not html:
            continue
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all("a", href=True):
            classes = set(tag.get("class") or [])
            href = tag.get("href", "")
            text = _clean_text(tag.get_text(" ", strip=True))
            if not href:
                continue
            absolute = urljoin(search_url, href)
            url = _unwrap_duckduckgo_url(absolute)
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if "duckduckgo.com" in parsed.netloc:
                continue
            if classes and not ({"result__a", "result-link"} & classes):
                if "result" not in " ".join(classes):
                    continue
            if not text and "uddg=" not in href:
                continue
            results.append(SearchResult(title=text, url=url))
            if len(results) >= num:
                return results
        if results:
            break
    return results
