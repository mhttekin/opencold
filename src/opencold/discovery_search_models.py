"""Search result model for discovery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchResult:
    """A single search result with title, URL, and optional snippet."""

    title: str
    url: str
    snippet: str = ""
    published_date: str = ""  # ISO date or relative date from search engine
    engine: str = ""  # Which search engine returned this result
