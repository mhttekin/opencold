from __future__ import annotations

from urllib.parse import quote_plus

from opencold import enricher
from opencold.discovery_data import (
    SEARCH_TIMEOUT,
)


def _duckduckgo_search_urls(query: str) -> list[str]:
    encoded = quote_plus(query)
    return [
        f"https://html.duckduckgo.com/html/?q={encoded}",
        f"https://lite.duckduckgo.com/lite/?q={encoded}",
    ]


def _fetch_search_html(url: str) -> str | None:
    return enricher._fetch_html(url, timeout=SEARCH_TIMEOUT)
