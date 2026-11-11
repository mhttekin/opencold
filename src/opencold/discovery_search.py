from __future__ import annotations

from opencold.discovery_search_fallback import _ddg_html_search
from opencold.discovery_search_models import SearchResult
from opencold.discovery_search_primary import _brave_search, _ddgs_search, _serper_search


def web_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search the web: ddgs → Brave → Serper → DDG HTML."""
    # 1. ddgs package — zero-auth, best option
    results = _ddgs_search(query, num)
    if results:
        return results
    # 2. Brave Search — zero-auth HTML scraping
    results = _brave_search(query, num)
    if results:
        return results
    # 3. Serper API — paid but reliable
    results = _serper_search(query, num)
    if results:
        return results
    # 4. DDG HTML scraping — last resort
    return _ddg_html_search(query, num)
