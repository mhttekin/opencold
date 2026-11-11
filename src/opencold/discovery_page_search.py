"""Search-based discovery of company-owned contact/team pages."""

from __future__ import annotations

from urllib.parse import urlparse

from opencold import enricher
from opencold.discovery_data import (
    SEARCH_FETCH_MULTIPLIER,
    SEARCH_PAGE_LIMIT,
    SEARCH_PATH_HINTS,
    SEARCH_QUERIES,
    SEARCH_RESULT_LIMIT,
)
from opencold.discovery_domains import _is_blocked_host, normalize_domain
from opencold.discovery_models import CandidateCompany
from opencold.discovery_search import web_search


def _search_result_allowed(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if normalize_domain(url) != domain:
        return False
    if _is_blocked_host(parsed.netloc):
        return False
    path = parsed.path.lower()
    if not path or path == "/":
        return False
    if any(
        ext in path for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip")
    ):
        return False
    if any(
        skip in path
        for skip in ("login", "signin", "sign-up", "signup", "privacy", "terms", "cookie")
    ):
        return False
    return any(hint in path for hint in SEARCH_PATH_HINTS)


def search_company_page_urls(
    company: CandidateCompany, limit: int = SEARCH_RESULT_LIMIT
) -> list[str]:
    """Find likely company-owned contact/team pages via web search."""
    domain = normalize_domain(company.website)
    urls = []
    seen: set[str] = set()
    for template in SEARCH_QUERIES:
        query = template.format(company=company.company, domain=domain)
        for result in web_search(query, num=limit):
            if not _search_result_allowed(result.url, domain):
                continue
            normalized = urlparse(result.url)._replace(fragment="").geturl().rstrip("/")
            if normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)
            if len(urls) >= limit:
                return urls
        if urls:
            break
    return urls


def search_company_pages(
    company: CandidateCompany, limit: int = SEARCH_PAGE_LIMIT
) -> list[enricher.PageContent]:
    """Fetch useful company-owned pages found through public search results."""
    pages = []
    for url in search_company_page_urls(company, limit=limit * SEARCH_FETCH_MULTIPLIER):
        page = enricher.fetch_page(url)
        if page.status == "ok":
            pages.append(page)
        if len(pages) >= limit:
            break
    return pages


def _merge_pages(
    pages: list[enricher.PageContent], extra_pages: list[enricher.PageContent]
) -> list[enricher.PageContent]:
    seen = {page.url.rstrip("/") for page in pages}
    merged = list(pages)
    for page in extra_pages:
        normalized = page.url.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            merged.append(page)
    return merged
