"""Source-page company discovery: fetch listed sources and extract candidate companies."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from opencold import enricher
from opencold.discovery_data import CTA_TEXT, INTERNAL_DETAIL_HINTS, INTERNAL_SKIP_PARTS
from opencold.discovery_domains import (
    _clean_text,
    _company_from_anchor,
    _is_blocked_domain,
    _is_blocked_host,
    normalize_domain,
)
from opencold.discovery_models import CandidateCompany


def _fetch_source(source: str) -> str | None:
    source = source.strip()
    path = Path(source)
    if path.exists():
        return path.read_text(encoding="utf-8")
    if source.startswith("file://"):
        return Path(source[7:]).read_text(encoding="utf-8")
    return enricher._fetch_html(source)


def _clamp_workers(workers: int) -> int:
    return max(1, min(int(workers or 1), 8))


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_sources(path: str) -> list[str]:
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        # Fall back to project root so it works from any directory
        p = _PROJECT_ROOT / p
    p = p.resolve()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


def extract_companies_from_html(html: str, source_url: str) -> list[CandidateCompany]:
    soup = BeautifulSoup(html or "", "html.parser")
    source_domain = normalize_domain(source_url)
    candidates: dict[str, CandidateCompany] = {}

    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        absolute = urljoin(source_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if _is_blocked_host(parsed.netloc):
            continue
        domain = normalize_domain(absolute)
        if _is_blocked_domain(domain, source_domain):
            continue
        website = f"{parsed.scheme}://{domain}"
        candidates.setdefault(
            domain,
            CandidateCompany(
                company=_company_from_anchor(tag.get_text(" ", strip=True), domain),
                website=website,
                discovery_source_url=source_url,
                discovery_reason=f"linked from source page: {_clean_text(tag.get_text(' ', strip=True)) or domain}",
            ),
        )

    return list(candidates.values())


def _internal_detail_links(html: str, source_url: str, limit: int = 30) -> list[str]:
    """Find likely same-site detail pages that may contain outbound company URLs."""
    soup = BeautifulSoup(html or "", "html.parser")
    source = urlparse(source_url if "://" in source_url else "https://" + source_url)
    source_domain = normalize_domain(source_url)
    links = []
    seen = set()
    for tag in soup.find_all("a", href=True):
        absolute = urljoin(source_url, tag.get("href", ""))
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if normalize_domain(absolute) != source_domain:
            continue
        path = parsed.path.lower()
        if path in {"", "/"} or any(part in path for part in INTERNAL_SKIP_PARTS):
            continue
        text = _clean_text(tag.get_text(" ", strip=True))
        likely_detail = any(hint in path for hint in INTERNAL_DETAIL_HINTS)
        if not likely_detail and (len(text) < 2 or CTA_TEXT.match(text)):
            continue
        normalized = f"{source.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            links.append(normalized)
        if len(links) >= limit:
            break
    return links


def discover_from_source(
    source: str, source_limit: int = 25, follow_internal: bool = True
) -> list[CandidateCompany]:
    """Discover company candidates from one source page and likely detail pages."""
    html = _fetch_source(source)
    if not html:
        return []
    candidates = extract_companies_from_html(html, source)
    seen = {normalize_domain(c.website) for c in candidates}
    if follow_internal and len(candidates) < source_limit:
        for link in _internal_detail_links(html, source, limit=max(source_limit * 2, 10)):
            detail_html = _fetch_source(link)
            if not detail_html:
                continue
            for candidate in extract_companies_from_html(detail_html, link):
                domain = normalize_domain(candidate.website)
                if domain not in seen:
                    seen.add(domain)
                    candidates.append(candidate)
                if len(candidates) >= source_limit:
                    break
            if len(candidates) >= source_limit:
                break
    return candidates[:source_limit]


def discover_companies(sources: list[str], limit: int = 50) -> list[CandidateCompany]:
    candidates: dict[str, CandidateCompany] = {}
    for source in sources:
        html = _fetch_source(source)
        if not html:
            continue
        for candidate in extract_companies_from_html(html, source):
            domain = normalize_domain(candidate.website)
            candidates.setdefault(domain, candidate)
            if len(candidates) >= limit:
                return list(candidates.values())
    return list(candidates.values())


def discover_company_pool(
    sources: list[str],
    limit: int = 50,
    source_limit: int = 25,
    workers: int = 8,
) -> list[CandidateCompany]:
    """Collect candidates across all sources before ranking/truncation."""
    candidates: dict[str, CandidateCompany] = {}
    workers = _clamp_workers(workers)

    def parse_source(source: str) -> list[CandidateCompany]:
        return discover_from_source(source, source_limit=source_limit, follow_internal=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_source = {executor.submit(parse_source, source): source for source in sources}
        for future in as_completed(future_to_source):
            for candidate in future.result():
                domain = normalize_domain(candidate.website)
                candidates.setdefault(domain, candidate)

    # Keep a larger pool than final output — we need extra candidates to replace
    # dropped leads (bad contacts, useless inboxes, stale employees, etc.)
    pool_size = max(limit * 5, limit + 20)
    return list(candidates.values())[:pool_size]
