from __future__ import annotations

from urllib.parse import urljoin, urlparse

from opencold import enricher
from opencold.discovery_data import (
    DISCOVERY_PATHS,
)


def crawl_company_pages(website: str, max_pages: int = 5) -> list[enricher.PageContent]:
    """Crawl pages useful for both company facts and public contacts."""
    base = enricher.normalize_url(website)
    if not base:
        return []
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    pages = []
    for path in DISCOVERY_PATHS[:max_pages]:
        url = origin if not path else urljoin(origin, path)
        page = enricher.fetch_page(url)
        if page.status == "ok":
            pages.append(page)
    return pages
