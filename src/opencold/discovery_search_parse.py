from __future__ import annotations

from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from opencold.discovery_domains import (
    _clean_text,
)


def _unwrap_duckduckgo_url(href: str) -> str:
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc:
        query = parse_qs(parsed.query)
        if query.get("uddg"):
            return unquote(query["uddg"][0])
    return href


def parse_search_result_urls(html: str, base_url: str = "https://duckduckgo.com") -> list[str]:
    """Parse organic result URLs from DuckDuckGo HTML/Lite result pages."""
    soup = BeautifulSoup(html or "", "html.parser")
    urls = []
    seen = set()

    for tag in soup.find_all("a", href=True):
        classes = set(tag.get("class") or [])
        href = tag.get("href", "")
        text = _clean_text(tag.get_text(" ", strip=True))
        if not href:
            continue
        absolute = urljoin(base_url, href)
        url = _unwrap_duckduckgo_url(absolute)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if "duckduckgo.com" in parsed.netloc:
            continue
        if classes and not ({"result__a", "result-link"} & classes):
            # Lite result links often have no useful class, so only use this as
            # a weak filter when class metadata exists.
            if "result" not in " ".join(classes):
                continue
        if not text and "uddg=" not in href:
            continue
        normalized = parsed._replace(fragment="").geturl().rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls
