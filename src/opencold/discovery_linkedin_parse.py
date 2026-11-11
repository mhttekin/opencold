from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from opencold.discovery_data import (
    LINKEDIN_TITLE_RE,
)
from opencold.discovery_domains import (
    _clean_text,
)
from opencold.discovery_person_score import (
    _valid_person_name,
)
from opencold.discovery_search_parse import _unwrap_duckduckgo_url


def parse_linkedin_result_titles(html: str) -> list[tuple[str, str, str, str]]:
    """Extract (name, role, company, linkedin_url) from DDG results linking to LinkedIn profiles."""
    soup = BeautifulSoup(html or "", "html.parser")
    results: list[tuple[str, str, str, str]] = []
    seen_names: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        absolute = urljoin("https://duckduckgo.com", href)
        url = _unwrap_duckduckgo_url(absolute)
        if "linkedin.com/in" not in url:
            continue
        text = _clean_text(tag.get_text(" ", strip=True))
        if not text:
            continue
        match = LINKEDIN_TITLE_RE.match(text)
        if not match:
            continue
        name = match.group("name").strip()
        role = match.group("role").strip()
        company = match.group("company").strip()
        if name.lower() in seen_names:
            continue
        if not _valid_person_name(name):
            continue
        seen_names.add(name.lower())
        results.append((name, role, company, url))
    return results
