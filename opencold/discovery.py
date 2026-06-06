"""Source-grounded company and contact discovery."""

from __future__ import annotations

import csv
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.request
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from opencold import enricher


BLOCKED_DOMAINS = {
    "apple.com",
    "apps.apple.com",
    "cdn.jsdelivr.net",
    "cloudflare.com",
    "facebook.com",
    "github.com",
    "github.io",
    "google.com",
    "googletagmanager.com",
    "instagram.com",
    "linkedin.com",
    "maps.google.com",
    "medium.com",
    "notion.site",
    "reddit.com",
    "twitter.com",
    "x.com",
    "youtube.com",
}

BLOCKED_HOST_PARTS = (
    "accounts.",
    "api.",
    "app.",
    "blog.",
    "cdn.",
    "docs.",
    "help.",
    "login.",
    "status.",
    "support.",
)

INTERNAL_SKIP_PARTS = (
    "about",
    "account",
    "advertise",
    "blog",
    "category",
    "contact",
    "cookie",
    "login",
    "privacy",
    "submit",
    "sign-in",
    "signin",
    "sign-up",
    "signup",
    "tag",
    "terms",
)

INTERNAL_DETAIL_HINTS = (
    "/ai/",
    "/app/",
    "/apps/",
    "/company/",
    "/companies/",
    "/directory/",
    "/product/",
    "/products/",
    "/startup/",
    "/startups/",
    "/tool/",
    "/tools/",
)

GENERIC_ICP_TERMS = {
    "startup",
    "startups",
    "company",
    "companies",
    "tool",
    "tools",
    "early",
    "software",
    "platform",
    "business",
}

ROLE_PREFIXES = {
    "contact",
    "founders",
    "growth",
    "hello",
    "hi",
    "info",
    "marketing",
    "partner",
    "partnerships",
    "press",
    "product",
    "sales",
    "security",
    "support",
    "team",
    "vulnerability-disclosure",
    "responsible-disclosure",
    "abuse",
    "admin",
    "billing",
    "careers",
    "compliance",
    "enquiries",
    "enquiry",
    "feedback",
    "general",
    "help",
    "hr",
    "jobs",
    "legal",
    "media",
    "newsletter",
    "noreply",
    "no-reply",
    "office",
    "postmaster",
    "pr",
    "privacy",
    "webmaster",
}

GUESSED_ROLE_EMAILS = ("hello", "contact", "sales", "partnerships")

HIGH_VALUE_ROLE_PREFIXES = {
    "partnerships",
    "partner",
    "growth",
    "marketing",
    "product",
    "sales",
    "team",
}

LOW_VALUE_ROLE_PREFIXES = {
    "founders",
    "hello",
    "hi",
    "contact",
    "press",
    "support",
    "info",
}

# Role inboxes useless for cold outreach — these go to support queues, not decision makers
OUTREACH_USELESS_PREFIXES = {
    "support",
    "contact",
    "info",
    "hello",
    "hi",
    "help",
    "noreply",
    "no-reply",
    "admin",
    "webmaster",
    "press",
    "media",
    "abuse",
    "postmaster",
    "billing",
    "legal",
    "security",
    "privacy",
    "compliance",
    "feedback",
    "newsletter",
    "jobs",
    "careers",
    "hr",
    "office",
    "general",
    "enquiries",
    "enquiry",
    "pr",
    "vulnerability-disclosure",
    "responsible-disclosure",
}

RELEVANT_ROLE_RE = re.compile(
    r"\b("
    r"partnerships?|partner|growth|marketing|product marketing|"
    r"developer relations|devrel|community|sales|business development|"
    r"customer success|recruiting|talent|engineering|developer advocate"
    r")\b",
    re.IGNORECASE,
)

EXEC_ROLE_RE = re.compile(r"\b(founder|co-founder|ceo|cto|cfo|coo|president)\b", re.IGNORECASE)

DISCOVERY_PATHS = (
    "",
    "/about",
    "/contact",
    "/team",
    "/founders",
    "/company",
    "/press",
    "/security",
    "/legal",
    "/imprint",
    "/careers",
)

SEARCH_QUERIES = (
    "site:{domain} contact",
    "site:{domain} team OR people",
    "site:{domain} partnerships OR partner",
    "site:{domain} developer relations OR devrel",
    "site:{domain} growth OR marketing",
    '"{company}" "{domain}" email',
)

SEARCH_RESULT_LIMIT = 8
SEARCH_PAGE_LIMIT = 4
SEARCH_FETCH_MULTIPLIER = 3
SEARCH_TIMEOUT = 3.0

# LinkedIn contact discovery via DuckDuckGo search result titles.
LINKEDIN_SEARCH_QUERIES = (
    '"{company}" marketing manager site:linkedin.com/in',
    '"{company}" partnerships site:linkedin.com/in',
    '"{company}" head of growth site:linkedin.com/in',
    '"{company}" customer success site:linkedin.com/in',
    '"{company}" business development site:linkedin.com/in',
    '"{company}" developer relations site:linkedin.com/in',
    '"{company}" sales manager site:linkedin.com/in',
    '"{company}" community manager site:linkedin.com/in',
)

LINKEDIN_TITLE_RE = re.compile(
    r"^(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*[-\u2013\u2014]\s*"
    r"(?P<role>[^|\u2013\u2014]+?)\s*[-\u2013\u2014]\s*(?P<company>[^|]+?)\s*\|\s*LinkedIn",
)

LINKEDIN_TARGET_ROLES_RE = re.compile(
    r"(?i:market|partner|growth|customer success|business develop|"
    r"developer relat|devrel|community|sales|account|outreach|demand gen|"
    r"talent|recruiting|people ops)",
)

_LINKEDIN_QUERY_DELAY = 1.5
_LINKEDIN_MAX_QUERIES = 3
_VERIFY_EMPLOYMENT = True

# Patterns indicating someone moved to a different company.
# Company name group: one or more capitalized words (e.g. "HubSpot", "Acme Corp").
# Stops at lowercase words, digits-only tokens, or punctuation.
_COMPANY_NAME_PAT = r"[A-Z][A-Za-z0-9]*(?:\s+(?:[A-Z&][A-Za-z0-9]*|[A-Z]+))*"
_MOVED_PATTERNS = re.compile(
    r"(?:"
    rf"[Nn]ow\s+(?:at|with|@)\s+(?P<new1>{_COMPANY_NAME_PAT})"
    rf"|[Jj]oined\s+(?P<new2>{_COMPANY_NAME_PAT})"
    rf"|[Mm]oved\s+to\s+(?P<new3>{_COMPANY_NAME_PAT})"
    rf"|[Cc]urrently\s+(?:at|with|@)\s+(?P<new4>{_COMPANY_NAME_PAT})"
    r")"
)
_NOT_EMPLOYED_RE = re.compile(
    r"(?i:opentowork|open to work|laid off|looking for|seeking.*opportunit|between roles|"
    r"available for hire|freelanc|independent consultant)",
)

# Matches LinkedIn date ranges like "Jan 2023 - Present", "Mar 2021 - Dec 2023"
_EMPLOYMENT_DATE_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{4})"
    r"\s*[-–—]\s*"
    r"(Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})",
    re.IGNORECASE,
)

# SearXNG public instances to try (rotated for load distribution)
_SEARXNG_INSTANCES = (
    "https://search.sapti.me",
    "https://searx.be",
    "https://searxng.site",
)

COMPANY_SUFFIXES_RE = re.compile(
    r"\s*\b(inc\.?|ltd\.?|llc\.?|corp\.?|co\.?|plc\.?|gmbh|s\.?a\.?|"
    r"pvt\.?\s*ltd\.?|limited|incorporated|corporation|company)\s*$",
    re.IGNORECASE,
)

SEARCH_PATH_HINTS = (
    "about",
    "business-development",
    "careers",
    "community",
    "company",
    "contact",
    "developer",
    "developers",
    "devrel",
    "growth",
    "marketing",
    "partners",
    "partnership",
    "partnerships",
    "people",
    "press",
    "sales",
    "security",
    "team",
)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
CTA_TEXT = re.compile(r"^(visit|visit website|website|open|learn more|view|go|launch|try it|demo)\s*(→|->)?$", re.IGNORECASE)
PERSON_LOCAL_RE = re.compile(r"^[a-z]+([._\-][a-z]+)?$")
PERSON_HINT_RE = re.compile(
    r"\b(?P<role>(?i:founder|co-founder|ceo|cto|cfo|coo|cpo|president|"
    r"head of [a-z]+|vp of [a-z]+|director of [a-z]+|"
    r"developer relations|devrel|growth|marketing|product|partnerships?|"
    r"community|sales|business development|customer success|recruiting|talent))"
    r"\b[:\s,-]+(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
)
PERSON_REVERSE_HINT_RE = re.compile(
    r"\b(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})"
    r"\b[,:\s-]+(?P<role>(?i:founder|co-founder|ceo|cto|cfo|coo|cpo|president|"
    r"head of [a-z]+|vp of [a-z]+|director of [a-z]+|"
    r"developer relations|devrel|growth|marketing|product|partnerships?|"
    r"community|sales|business development|customer success|recruiting|talent))\b",
)
BAD_PERSON_WORDS = {
    "About",
    "All",
    "And",
    "Careers",
    "Company",
    "Contact",
    "Co",
    "Home",
    "Legal",
    "Needle",
    "Press",
    "Privacy",
    "Processing",
    "Read",
    "Run",
    "Security",
    "Support",
    "Team",
    "Terms",
    "The",
    "We",
}
NOISY_PRODUCT_RE = re.compile(
    r"\b("
    r"directory|directories|backlink|submit your|submit ai|resume|cv|"
    r"video generator|audio tool|vocal remover|asmr|karaoke|wallpaper|"
    r"headshot|logo generator|image generator|tiktok|instagram"
    r")\b",
    re.IGNORECASE,
)
B2B_SIGNAL_RE = re.compile(
    r"\b("
    r"api|developer|developers|engineering|observability|analytics|crm|"
    r"workflow|workflows|infrastructure|security|database|data|agent|agents|"
    r"sdk|cloud|enterprise|saas|support|automation|billing|auth|monitoring"
    r")\b",
    re.IGNORECASE,
)


@dataclass
class CandidateCompany:
    company: str
    website: str
    discovery_source_url: str
    discovery_reason: str
    discovery_channel: str = ""


@dataclass
class Contact:
    name: str = ""
    role: str = ""
    email: str = ""
    contact_type: str = ""
    confidence: int = 0
    source_url: str = ""


def _clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


# Second-level labels under a 2-letter ccTLD that are public suffixes, not the
# registrable name (e.g. gov.bd, ac.uk, or.jp). Keeps jbc.gov.bd from collapsing
# to gov.bd. Triggered only when the final label is a 2-letter ccTLD.
_SECOND_LEVEL_TLDS = {
    "co", "com", "net", "org", "gov", "govt", "edu", "ac", "mil",
    "go", "or", "ne", "gob", "gouv",
}


def _registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_TLDS and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def normalize_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    return _registrable_domain(parsed.netloc or parsed.path)


def _is_blocked_domain(domain: str, source_domain: str = "") -> bool:
    if not domain or domain == source_domain:
        return True
    if domain in BLOCKED_DOMAINS:
        return True
    return any(domain.endswith("." + blocked) for blocked in BLOCKED_DOMAINS)


def _is_blocked_host(host: str) -> bool:
    host = host.lower()
    return any(part in host for part in BLOCKED_HOST_PARTS)


def _company_from_domain(domain: str) -> str:
    stem = domain.split(".")[0]
    return stem.replace("-", " ").replace("_", " ").title()


def _company_from_anchor(text: str, domain: str) -> str:
    text = _clean_text(text)
    if CTA_TEXT.match(text):
        return _company_from_domain(domain)
    if 2 <= len(text) <= 60 and not text.lower().startswith(("http", "www.")):
        return text
    return _company_from_domain(domain)


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


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def discover_from_source(source: str, source_limit: int = 25, follow_internal: bool = True) -> list[CandidateCompany]:
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


def _duckduckgo_search_urls(query: str) -> list[str]:
    encoded = quote_plus(query)
    return [
        f"https://html.duckduckgo.com/html/?q={encoded}",
        f"https://lite.duckduckgo.com/lite/?q={encoded}",
    ]


def _fetch_search_html(url: str) -> str | None:
    return enricher._fetch_html(url, timeout=SEARCH_TIMEOUT)


# ---------------------------------------------------------------------------
# Unified search: Serper API (preferred) with DDG HTML fallback
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single search result with title, URL, and optional snippet."""
    title: str
    url: str
    snippet: str = ""
    published_date: str = ""  # ISO date or relative date from search engine
    engine: str = ""  # Which search engine returned this result


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
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            ))
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
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("href", ""),
                snippet=item.get("body", ""),
                engine="ddgs",
            ))
        return results
    except Exception:
        return []


def _brave_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using Brave Search HTML (zero-auth fallback)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://search.brave.com/search?q={encoded}"
        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en-US,en;q=0.9",
        })
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
                title = text[text.index(slug) + len(slug):]
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


def _mojeek_search(query: str, num: int = 10) -> list[SearchResult]:
    """Search using Mojeek HTML (zero-auth, independent index)."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.mojeek.com/search?q={encoded}"
        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
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
                results.append(SearchResult(
                    title=title, url=href, snippet=snippet,
                    published_date=pub_date, engine="mojeek",
                ))
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
            req = urllib.request.Request(url, headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            })
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
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=result_url,
                    snippet=item.get("content", ""),
                    published_date=pub_date,
                    engine=f"searxng({engines})" if engines else "searxng",
                ))
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


# ---------------------------------------------------------------------------
# Company name → website resolution (for CSVs that only have company names)
# ---------------------------------------------------------------------------

# Aggregator / directory / marketplace domains that are never a company's own
# site — used to skip false positives when resolving a website from a name.
WEBSITE_DIRECTORY_DOMAINS = {
    "amazon.com",
    "angel.co",
    "apollo.io",
    "apps.apple.com",
    "bbb.org",
    "bloomberg.com",
    "builtwith.com",
    "businesswire.com",
    "capterra.com",
    "clearbit.com",
    "crunchbase.com",
    "dnb.com",
    "f6s.com",
    "g2.com",
    "getapp.com",
    "glassdoor.com",
    "indeed.com",
    "leadiq.com",
    "manta.com",
    "owler.com",
    "pitchbook.com",
    "play.google.com",
    "prnewswire.com",
    "producthunt.com",
    "rocketreach.co",
    "semrush.com",
    "similarweb.com",
    "softwareadvice.com",
    "tracxn.com",
    "trustpilot.com",
    "wellfound.com",
    "wikipedia.org",
    "wikimedia.org",
    "ycombinator.com",
    "yelp.com",
    "zoominfo.com",
}


def _company_tokens(company: str) -> list[str]:
    """Lowercase alphanumeric tokens of a company name, legal suffixes stripped."""
    cleaned = COMPANY_SUFFIXES_RE.sub("", company or "").strip().lower()
    return [t for t in re.split(r"[^a-z0-9]+", cleaned) if len(t) >= 2]


def _domain_matches_company(domain: str, tokens: list[str]) -> bool:
    """Heuristic: does a registrable domain plausibly belong to this company?"""
    if not tokens:
        return False
    stem = domain.split(".")[0].lower()
    if not stem:
        return False
    compact = "".join(tokens)
    if stem == compact or compact in stem or stem in compact:
        return True
    # A significant single token (>=4 chars) appearing in the domain stem
    return any(tok in stem for tok in tokens if len(tok) >= 4)


def _is_directory_domain(domain: str) -> bool:
    return domain in WEBSITE_DIRECTORY_DOMAINS or any(
        domain.endswith("." + d) for d in WEBSITE_DIRECTORY_DOMAINS
    )


def resolve_company_website(
    company: str,
    num: int = 8,
    require_match: bool = False,
    context: str = "",
    prefer_cc: str | None = None,
) -> str | None:
    """Resolve a company's official website URL from its name via web search.

    Uses the shared search stack (ddgs → Brave → Serper → DDG HTML), then picks
    the best organic result: a non-blocked, non-directory domain whose name
    matches the company. Falls back to the first credible organic domain when no
    name match is found. Returns 'https://domain' or None.

    require_match=True returns only a domain whose stem matches the company name
    (no fallback). Used for LLM-seeded company discovery, where accepting a
    non-matching domain (a media/jobs article about the company) would attach the
    wrong company to the lead — exactly the failure this pivot exists to avoid.

    context (e.g. "landscape United Kingdom") biases the search toward the right
    namesake. prefer_cc (e.g. "uk") makes a name-matching domain on that ccTLD win
    outright over a generic-TLD namesake — so "Ground Control" the UK landscaper
    (groundcontrol.co.uk) beats "Ground Control" the IoT firm (groundcontrol.com).
    """
    tokens = _company_tokens(company)
    if not tokens:
        return None

    queries = []
    if context.strip():
        queries.append(f'"{company}" {context.strip()} official website')
    queries += [f"{company} official website", f'"{company}"']

    seen: set[str] = set()
    name_match: str | None = None
    fallback: str | None = None

    for query in queries:
        for result in web_search(query, num=num):
            parsed = urlparse(result.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if _is_blocked_host(parsed.netloc):
                continue
            domain = normalize_domain(result.url)
            if not domain or domain in seen:
                continue
            seen.add(domain)
            if _is_blocked_domain(domain) or _is_directory_domain(domain):
                continue
            matched = _domain_matches_company(domain, tokens)
            on_cc = bool(prefer_cc) and (domain.endswith("." + prefer_cc) or domain.rsplit(".", 1)[-1] == prefer_cc)
            if matched and on_cc:
                return f"https://{domain}"          # right name AND right country
            if matched and name_match is None:
                name_match = f"https://{domain}"
            if fallback is None:
                fallback = f"https://{domain}"
        # Stop early only when we don't need to keep hunting for a ccTLD match.
        if name_match and not prefer_cc:
            break
        if fallback and not require_match and not prefer_cc:
            break

    if name_match:
        return name_match
    return None if require_match else fallback


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
        if classes and not ({"result__a", "result-link", "result-link"} & classes):
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


# ---------------------------------------------------------------------------
# LinkedIn contact discovery via DuckDuckGo search result metadata
# ---------------------------------------------------------------------------

def _company_name_matches(candidate: str, target: str) -> bool:
    """Fuzzy-match a company name from a LinkedIn title against the target."""
    def _normalize(name: str) -> str:
        return COMPANY_SUFFIXES_RE.sub("", name).strip().lower()

    c = _normalize(candidate)
    t = _normalize(target)
    if not c or not t:
        return False
    if c == t:
        return True
    # For short single-word company names, require exact word boundary match
    # to avoid "Framer" matching "Framerfry" or "FramerExperts"
    if " " not in t and len(t) <= 10:
        # Target is a short single word — only match if it appears as a
        # standalone word in the candidate, or candidate is contained in target
        if c in t:
            return True
        if re.search(r"\b" + re.escape(t) + r"\b", c):
            return True
        return False
    if c in t or t in c:
        return True
    c_tokens = set(c.split())
    t_tokens = set(t.split())
    if not c_tokens or not t_tokens:
        return False
    overlap = len(c_tokens & t_tokens) / max(len(c_tokens), len(t_tokens))
    return overlap > 0.5


def _is_name_company_coincidence(name: str, company: str, linkedin_url: str) -> bool:
    """Detect when a person's name coincidentally matches the company name.

    Example: "Matt Crisp" found for company "Crisp" — the URL /in/mattcrisp
    is just the person's name, and "Crisp" in the LinkedIn title is their
    surname, not their employer.
    """
    name_parts = name.lower().split()
    if len(name_parts) < 2:
        return False
    company_lower = company.lower().strip()
    first_name = name_parts[0]
    last_name = name_parts[-1]
    # Check if person's first or last name matches the company name
    name_matches_company = (
        last_name == company_lower or company_lower in last_name
        or first_name == company_lower
    )
    if not name_matches_company:
        return False

    # If the person's last name IS the company name (single-word company),
    # this is very likely a coincidence — verify via URL slug
    slug = linkedin_url.rstrip("/").rsplit("/", 1)[-1].lower()
    # Remove LinkedIn dedup suffixes (e.g., -258a1651, -3a69205, -12345)
    slug_clean = re.sub(r"[-_][0-9a-f]{4,}$", "", slug)
    slug_clean = re.sub(r"[-_]?\d+$", "", slug_clean)

    # Build expected slug patterns from the name
    first = name_parts[0]
    name_slugs = {
        f"{first}{last_name}",           # mattcrisp
        f"{first}-{last_name}",          # matt-crisp
        f"{first}_{last_name}",          # matt_crisp
        f"{last_name}{first}",           # crispmatt
        f"{last_name}-{first}",          # crisp-matt
        f"{first}{last_name[0]}",        # mattc
        f"{first[0]}{last_name}",        # mcrisp
    }
    # For multi-part names (e.g., "Mixo Oral Baloyi"), also try middle+last combos
    if len(name_parts) > 2:
        middle_parts = name_parts[1:-1]
        for mid in middle_parts:
            name_slugs.add(f"{first}-{mid}-{last_name}")
            name_slugs.add(f"{first}{mid}{last_name}")
    if slug_clean in name_slugs:
        return True

    # For single-word short company names that match the person's first or last name,
    # the coincidence rate is very high (e.g., "Crisp" company matching anyone named Crisp,
    # or "Mixo" company matching someone whose first name is Mixo).
    matching_name = None
    if " " not in company_lower:
        if last_name == company_lower:
            matching_name = last_name
        elif first_name == company_lower:
            matching_name = first_name
    if matching_name:
        # If slug doesn't contain the company name as part of a non-name pattern,
        # it's likely a name coincidence
        if company_lower not in slug_clean:
            return True
        # If slug IS a name pattern even after not matching our exact patterns above,
        # check if it's very short or random (like 'label23') — still a coincidence
        if len(slug_clean) < 10 and not any(c in slug_clean for c in company_lower):
            return True

    return False


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


# ---------------------------------------------------------------------------
# Email pattern guessing with reacher verification
# ---------------------------------------------------------------------------

_REACHER_VERSION = "0.11.7"
_REACHER_BIN_DIR = Path(__file__).resolve().parent.parent / "vendor" / "bin"
_REACHER_BIN_NAME = "check_if_email_exists"

# Cache for reacher binary availability
_REACHER_BIN: str | None | bool = None  # None = unchecked, False = not found


def _reacher_target_triple() -> str | None:
    """Return the GitHub release target triple for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        # No arm64 macOS build — x86_64 works under Rosetta 2
        return "x86_64-apple-darwin"
    if system == "linux":
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"
    return None


def _download_reacher() -> str | None:
    """Download the check-if-email-exists binary into vendor/bin/."""
    triple = _reacher_target_triple()
    if not triple:
        return None
    url = (
        f"https://github.com/reacherhq/check-if-email-exists/releases/download/"
        f"v{_REACHER_VERSION}/check_if_email_exists-{triple}.tar.gz"
    )
    _REACHER_BIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = _REACHER_BIN_DIR / _REACHER_BIN_NAME
    try:
        tar_path = _REACHER_BIN_DIR / f"reacher-{triple}.tar.gz"
        req = urllib.request.Request(url, headers={"User-Agent": "opencold/0.1"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(tar_path, "wb") as f:
            f.write(resp.read())
        with tarfile.open(tar_path, "r:gz") as tar:
            # Security: only extract the expected binary name
            members = [m for m in tar.getmembers() if os.path.basename(m.name) == _REACHER_BIN_NAME]
            if not members:
                return None
            member = members[0]
            member.name = _REACHER_BIN_NAME  # flatten path
            tar.extract(member, path=_REACHER_BIN_DIR, filter="data")
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        tar_path.unlink(missing_ok=True)
        return str(dest)
    except Exception:
        return None


def _find_reacher_binary() -> str | None:
    """Find the check-if-email-exists binary: vendor/bin → PATH → auto-download."""
    global _REACHER_BIN
    if _REACHER_BIN is None:
        # 1. Check vendor/bin (bundled with project)
        vendor_path = _REACHER_BIN_DIR / _REACHER_BIN_NAME
        if vendor_path.is_file():
            _REACHER_BIN = str(vendor_path)
        else:
            # 2. Check PATH
            on_path = shutil.which("check_if_email_exists") or shutil.which("check-if-email-exists")
            if on_path:
                _REACHER_BIN = on_path
            else:
                # 3. Auto-download
                downloaded = _download_reacher()
                _REACHER_BIN = downloaded if downloaded else False
    return _REACHER_BIN if _REACHER_BIN else None


def _reacher_check(email: str, from_email: str = "noreply@opencold.dev") -> dict | None:
    """Call check-if-email-exists CLI to verify an email address.

    Returns the parsed JSON result, or None if the binary is unavailable or errors.
    """
    binary = _find_reacher_binary()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--from-email", from_email, email],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def _generate_email_patterns(first: str, last: str, domain: str) -> list[str]:
    """Generate common email address patterns from first/last name."""
    patterns = [
        f"{first}.{last}@{domain}",      # jane.smith@
        f"{first}@{domain}",              # jane@
        f"{first}{last}@{domain}",        # janesmith@
        f"{first[0]}{last}@{domain}",     # jsmith@
        f"{first}{last[0]}@{domain}",     # janes@
        f"{first[0]}.{last}@{domain}",    # j.smith@
        f"{last}.{first}@{domain}",       # smith.jane@
        f"{first}_{last}@{domain}",       # jane_smith@
        f"{first}-{last}@{domain}",       # jane-smith@
    ]
    return patterns


def _guess_email_from_name(name: str, domain: str) -> str | None:
    """Try multiple email patterns for a person and validate with reacher.

    Falls back to first.last@domain with MX-only check if reacher is not installed.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return None
    first = parts[0].lower()
    last = parts[-1].lower()

    # Quick MX check first — no point trying patterns if domain doesn't accept mail
    try:
        from opencold.verifier import _check_mx
        if not _check_mx(domain):
            return None
    except Exception:
        pass

    # If reacher binary is available, try all patterns
    if _find_reacher_binary():
        candidates = _generate_email_patterns(first, last, domain)
        reacher_failed = False
        all_invalid = True
        for email in candidates:
            result = _reacher_check(email)
            if result is None:
                reacher_failed = True
                break  # binary failed, fall back
            reachable = result.get("is_reachable", "unknown")
            if reachable == "safe":
                return email
            if reachable == "risky":
                # Catch-all domains accept everything — return first.last as best guess
                smtp = result.get("smtp", {})
                if smtp.get("is_catch_all"):
                    return candidates[0]  # first.last@ is most common
                return email
            if reachable != "invalid":
                all_invalid = False
            # "invalid" or "unknown" — try next pattern
        if not reacher_failed:
            if all_invalid:
                # Reacher confirmed no pattern exists — person likely doesn't work here
                return None
            # Mix of unknown/invalid — domain might block SMTP probes
            # Don't guess — return None to avoid sending to bad addresses
            return None

    # No reacher binary — don't guess, email verification is required
    return None


def _parse_linkedin_title(title: str) -> tuple[str, str, str] | None:
    """Parse a LinkedIn profile title into (name, role, company) or None."""
    m = LINKEDIN_TITLE_RE.match(title)
    if not m:
        return None
    name = m.group("name").strip()
    role = m.group("role").strip()
    company = m.group("company").strip()
    if not _valid_person_name(name):
        return None
    return name, role, company


def _company_in_title(title: str, company_lower: str, company_tokens: set[str]) -> bool:
    """Check if company name appears in a search result title."""
    title_lower = title.lower()
    if company_lower in title_lower:
        return True
    if len(company_tokens) > 1:
        found = sum(1 for t in company_tokens if t in title_lower)
        if found >= len(company_tokens) * 0.6:
            return True
    elif company_tokens:
        token = list(company_tokens)[0]
        if re.search(r"\b" + re.escape(token) + r"\b", title_lower):
            return True
    return False


_COMMON_ROLES_RE = re.compile(
    r"(?i:^(?:engineer|developer|designer|manager|director|analyst|consultant|"
    r"scientist|architect|lead|head|chief|vp|president|founder|ceo|cto|cfo|coo|"
    r"intern|associate|coordinator|specialist|strategist|officer|advisor|"
    r"professor|researcher|student|freelanc))",
)


def _extract_linkedin_company_from_title(title: str) -> str:
    """Extract the company name from a LinkedIn-style search result title.

    Handles formats:
      "Name - Role - Company | LinkedIn" → Company
      "Name - Company | LinkedIn" → Company  (if not a common role word)
    """
    parsed = _parse_linkedin_title(title)
    if parsed:
        return parsed[2]  # company field
    # Fallback: split by dashes and look for "... | LinkedIn" at the end
    parts = re.split(r"\s*[-–—]\s*", title)
    if len(parts) >= 2 and "linkedin" in parts[-1].lower():
        # Last part might be "Company | LinkedIn" or just "LinkedIn"
        last = parts[-1].split("|")[0].strip()
        if last.lower() == "linkedin":
            # The company is in the second-to-last part (for 3+ parts)
            if len(parts) >= 3:
                candidate = parts[-2].split("|")[0].strip()
                if not _COMMON_ROLES_RE.match(candidate):
                    return candidate
        elif last and not _COMMON_ROLES_RE.match(last):
            # "Name - Company | LinkedIn" → Company is before the pipe
            return last
    return ""


def _check_employment_dates(text: str, company: str) -> tuple[str, bool] | None:
    """Check for LinkedIn employment date ranges in text.

    Returns (date_range_str, is_current) or None if no dates found.
    """
    company_lower = company.lower()
    # Look for patterns like "Jan 2023 - Present" near the company name
    for m in _EMPLOYMENT_DATE_RE.finditer(text):
        # Check if company name is near this date range (within 200 chars)
        start = max(0, m.start() - 200)
        context = text[start:m.end() + 50].lower()
        if company_lower not in context:
            continue
        end_date = m.group(2).strip()
        date_str = m.group(0)
        is_current = end_date.lower() == "present"
        return date_str, is_current
    return None


def _analyze_engine_results(
    results: list[SearchResult], company: str
) -> dict:
    """Analyze a single engine's results for employment signals.

    Returns a dict with keys: confirms, contradicts, not_employed,
    moved_to, date_info, company_in_title, other_company.
    """
    analysis: dict = {
        "confirms": False,
        "contradicts": False,
        "not_employed": False,
        "moved_to": "",
        "date_info": None,  # (date_str, is_current) or None
        "company_in_title": False,
        "other_company": "",
        "published_dates": [],
    }

    company_lower = COMPANY_SUFFIXES_RE.sub("", company).strip().lower()
    company_tokens = set(company_lower.split())
    combined_text = " ".join(f"{r.title} {r.snippet}" for r in results)

    # Check for not-employed signals
    if _NOT_EMPLOYED_RE.search(combined_text):
        analysis["not_employed"] = True

    # Check for move signals
    match = _MOVED_PATTERNS.search(combined_text)
    if match:
        new_company = (
            match.group("new1") or match.group("new2")
            or match.group("new3") or match.group("new4") or ""
        ).strip()
        if new_company and not _company_name_matches(new_company, company):
            analysis["moved_to"] = new_company

    # Check LinkedIn titles — only process first ~120 chars to avoid DDG's
    # concatenated multi-result garbage titles
    for result in results:
        if "linkedin.com/in" not in result.url:
            continue
        # DDG sometimes concatenates multiple result titles; truncate to first
        title = result.title
        pipe_idx = title.find("| LinkedIn")
        if pipe_idx > 0:
            title = title[:pipe_idx + len("| LinkedIn")]

        if _company_in_title(title, company_lower, company_tokens):
            analysis["company_in_title"] = True
            analysis["confirms"] = True
        else:
            # Extract what company IS in the title
            other = _extract_linkedin_company_from_title(title)
            if other and not _company_name_matches(other, company):
                analysis["other_company"] = other
                analysis["contradicts"] = True

        # Check for employment dates in snippet
        date_info = _check_employment_dates(
            f"{title} {result.snippet}", company
        )
        if date_info:
            analysis["date_info"] = date_info

    # Collect published dates for recency comparison
    for result in results:
        if result.published_date:
            analysis["published_dates"].append(result.published_date)

    # Snippet-level confirmation — only if no LinkedIn title signals found
    # (snippets from non-LinkedIn pages like author bios can be misleading)
    if not analysis["confirms"] and not analysis["contradicts"]:
        snippet_text = " ".join(r.snippet for r in results).lower()
        if company_lower in snippet_text:
            analysis["confirms"] = True

    return analysis


def verify_current_employment(name: str, company: str) -> tuple[bool, str]:
    """Check if a person likely still works at the given company.

    Runs two DDG queries in parallel:
      1. "name" linkedin — general results, snippets with career signals
      2. "name" site:linkedin.com/in — LinkedIn-specific, fresher profile titles

    Brave/Mojeek/SearXNG are blocked by bot detection so we rely on DDG only
    but with two complementary query angles. Date ranges (e.g. "Jan 2023 -
    Present") and career-move signals are parsed. Returns (is_current, reason).
    """
    if not _VERIFY_EMPLOYMENT:
        return True, "verification_disabled"

    query_general = f'"{name}" linkedin'
    query_site = f'"{name}" site:linkedin.com/in'

    # Run both queries in parallel
    queries = {
        "ddgs_general": (query_general, _ddgs_search),
        "ddgs_site": (query_site, _ddgs_search),
    }
    engine_results: dict[str, list[SearchResult]] = {}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(fn, q, 5): label
            for label, (q, fn) in queries.items()
        }
        for future in as_completed(futures):
            label = futures[future]
            try:
                engine_results[label] = future.result()
            except Exception:
                engine_results[label] = []

    # Merge all results
    all_results: list[SearchResult] = []
    for results in engine_results.values():
        all_results.extend(results)

    if not all_results:
        return True, "no_results_benefit"

    # Analyze each query's results independently
    engine_analyses: dict[str, dict] = {}
    for label, results in engine_results.items():
        if results:
            engine_analyses[label] = _analyze_engine_results(results, company)

    if not engine_analyses:
        return True, "no_results_benefit"

    # The site: query is more authoritative for LinkedIn titles
    # (returns actual profile pages with current titles)
    site_analysis = engine_analyses.get("ddgs_site")
    general_analysis = engine_analyses.get("ddgs_general")

    # Aggregate signals
    any_confirms = any(a["confirms"] for a in engine_analyses.values())
    any_contradicts = any(a["contradicts"] for a in engine_analyses.values())
    any_not_employed = any(a["not_employed"] for a in engine_analyses.values())
    moved_to_companies = [a["moved_to"] for a in engine_analyses.values() if a["moved_to"]]
    other_companies = [a["other_company"] for a in engine_analyses.values() if a["other_company"]]
    confirming_sources = [e for e, a in engine_analyses.items() if a["confirms"]]
    contradicting_sources = [e for e, a in engine_analyses.items() if a["contradicts"]]

    # Check for employment dates
    date_infos = [a["date_info"] for a in engine_analyses.values() if a["date_info"]]
    for date_str, is_current in date_infos:
        if not is_current:
            return False, f"past_employment:{date_str}"
        if is_current and any_confirms:
            return True, f"date_confirms_current:{date_str}"

    # Not-employed signal is strong
    if any_not_employed:
        return False, "not_currently_employed"

    # Moved-to is strong
    if moved_to_companies:
        return False, f"moved_to:{moved_to_companies[0]}"

    # site: query contradicts → this is very reliable (fresh LinkedIn titles)
    if site_analysis and site_analysis["contradicts"] and not site_analysis["confirms"]:
        other = site_analysis["other_company"] or (other_companies[0] if other_companies else "unknown")
        return False, f"contradicted_by:linkedin_title:now_at:{other}"

    # Both queries confirm
    if any_confirms and not any_contradicts:
        sources_str = "+".join(confirming_sources)
        return True, f"confirmed_by:{sources_str}"

    # Only site: confirms → reliable
    if site_analysis and site_analysis["confirms"] and not any_contradicts:
        return True, "confirmed_by:linkedin_profile"

    # Contradicts without confirms
    if any_contradicts and not any_confirms:
        other = other_companies[0] if other_companies else "unknown"
        return False, f"contradicted_by:search:now_at:{other}"

    # DISAGREEMENT: site: says one thing, general says another
    if any_confirms and any_contradicts:
        # site: query is more authoritative
        if site_analysis:
            if site_analysis["confirms"] and not site_analysis["contradicts"]:
                return True, "disagreement:linkedin_confirms"
            if site_analysis["contradicts"] and not site_analysis["confirms"]:
                other = site_analysis["other_company"] or "unknown"
                return False, f"disagreement:linkedin_contradicts:{other}"
        # Neither query is clearly right
        return True, "disagreement:inconclusive"

    # No LinkedIn-specific signals — check snippets (only if company is long enough
    # to avoid false matches)
    company_lower = COMPANY_SUFFIXES_RE.sub("", company).strip().lower()
    if len(company_lower) > 4:
        all_snippets = " ".join(r.snippet for r in all_results).lower()
        if company_lower in all_snippets:
            return True, "snippet_confirms"

    # For short/generic company names, give benefit of doubt
    if len(company) <= 4:
        return True, "short_company_name_benefit"

    return False, "company_not_in_results"


def search_linkedin_contacts(
    company_name: str,
    domain: str,
    max_queries: int = _LINKEDIN_MAX_QUERIES,
) -> list["Contact"]:
    """Search for LinkedIn profiles matching the company via web search."""
    contacts: list[Contact] = []
    seen_names: set[str] = set()
    queries_made = 0

    for template in LINKEDIN_SEARCH_QUERIES:
        if queries_made >= max_queries:
            break
        query = template.format(company=company_name)
        if queries_made > 0:
            time.sleep(_LINKEDIN_QUERY_DELAY)
        queries_made += 1

        results = web_search(query, num=10)
        found_any = False
        for result in results:
            if "linkedin.com/in" not in result.url:
                continue
            parsed = _parse_linkedin_title(result.title)
            if not parsed:
                continue
            name, role, company_in_title = parsed
            if name.lower() in seen_names:
                continue
            if not _company_name_matches(company_in_title, company_name):
                continue
            # Skip name-company coincidences (e.g. "Matt Crisp" for company "Crisp")
            if _is_name_company_coincidence(name, company_name, result.url):
                continue
            seen_names.add(name.lower())
            confidence = 70 if LINKEDIN_TARGET_ROLES_RE.search(role) else 50
            contacts.append(Contact(
                name=name,
                role=role.strip().rstrip(",").strip(),
                contact_type="linkedin_profile",
                confidence=confidence,
                source_url=result.url,
            ))
            found_any = True
        if found_any:
            break  # short-circuit: first successful query is enough

    # Sort by role relevance: targeted roles first
    contacts.sort(key=lambda c: (0 if LINKEDIN_TARGET_ROLES_RE.search(c.role or "") else 1))

    # Verify employment for the top candidates
    if _VERIFY_EMPLOYMENT and contacts:
        verified: list[Contact] = []
        any_hard_reject = False
        for contact in contacts[:3]:  # Only verify top 3
            is_current, reason = verify_current_employment(contact.name, company_name)
            if is_current:
                confidence = contact.confidence
                if "disagreement" in reason:
                    confidence = max(confidence - 15, 30)
                verified.append(Contact(
                    name=contact.name,
                    role=contact.role,
                    contact_type=contact.contact_type,
                    confidence=confidence,
                    source_url=contact.source_url,
                ))
            elif "contradict" in reason or "moved_to" in reason or "not_currently" in reason:
                any_hard_reject = True
            time.sleep(0.3)
        if verified:
            return verified
        # Only use fallback for soft rejections (no results, search failed, etc.)
        # If verification explicitly contradicted, don't return the contact
        if not any_hard_reject and contacts[0].confidence >= 70:
            return [Contact(
                name=contacts[0].name,
                role=contacts[0].role,
                contact_type=contacts[0].contact_type,
                confidence=max(contacts[0].confidence - 20, 30),
                source_url=contacts[0].source_url,
            )]
        return []

    return contacts


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
    if any(ext in path for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip")):
        return False
    if any(skip in path for skip in ("login", "signin", "sign-up", "signup", "privacy", "terms", "cookie")):
        return False
    return any(hint in path for hint in SEARCH_PATH_HINTS)


def search_company_page_urls(company: CandidateCompany, limit: int = SEARCH_RESULT_LIMIT) -> list[str]:
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


def search_company_pages(company: CandidateCompany, limit: int = SEARCH_PAGE_LIMIT) -> list[enricher.PageContent]:
    """Fetch useful company-owned pages found through public search results."""
    pages = []
    for url in search_company_page_urls(company, limit=limit * SEARCH_FETCH_MULTIPLIER):
        page = enricher.fetch_page(url)
        if page.status == "ok":
            pages.append(page)
        if len(pages) >= limit:
            break
    return pages


def _merge_pages(pages: list[enricher.PageContent], extra_pages: list[enricher.PageContent]) -> list[enricher.PageContent]:
    seen = {page.url.rstrip("/") for page in pages}
    merged = list(pages)
    for page in extra_pages:
        normalized = page.url.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            merged.append(page)
    return merged


def _icp_terms(icp: str) -> set[str]:
    return {
        term.lower()
        for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-]{2,}", icp or "")
        if term.lower() not in {"and", "for", "the", "with", "that", "this"} | GENERIC_ICP_TERMS
    }


def score_company(company: CandidateCompany, enrichment: dict, icp: str) -> tuple[int, str]:
    # NOTE: company.discovery_reason is deliberately excluded — for LLM/search
    # candidates it echoes our own query (e.g. "llm seed: landscape in UK"), so
    # including it made every lead "match" the ICP (a constant 62). Match against
    # the company's own name and crawled content only.
    terms = _icp_terms(icp)
    haystack = " ".join([
        company.company,
        enrichment.get("company_summary", ""),
        enrichment.get("personalization_facts", ""),
    ]).lower()
    matched = sorted(term for term in terms if term in haystack)
    base = 35 if enrichment.get("website_status") == "ok" else 15
    match_bonus = min(len(matched) * 14, 50)
    score = min(100, base + match_bonus)
    return score, enricher.FACT_SEPARATOR.join(matched)


def _icp_evidence(icp: str, enrichment: dict) -> bool:
    """True when ICP terms appear in the company's own crawled content.

    Content-only (no company name, no discovery_reason): this is the evidence
    used to gate leads, so it must reflect what the site actually says — a company
    literally named 'X Landscapes' should still have to prove it on its pages.
    """
    terms = _icp_terms(icp)
    if not terms:
        return False
    content = " ".join([
        enrichment.get("company_summary", ""),
        enrichment.get("personalization_facts", ""),
    ]).lower()
    return any(term in content for term in terms)


def _bad_company_name(company: str) -> bool:
    value = _clean_text(company)
    if not value:
        return True
    if CTA_TEXT.match(value):
        return True
    if value.isdigit():
        return True
    if len(value) > 42:
        return True
    return False


def score_lead(row: dict) -> tuple[int, str]:
    """Score final discovered lead quality for ranking and review."""
    score = 35
    reasons = []

    name = row.get("company", "")
    facts = " ".join([
        row.get("discovery_reason", ""),
        row.get("company_summary", ""),
        row.get("personalization_facts", ""),
    ])
    facts_lower = facts.lower()

    if _bad_company_name(name):
        score -= 20
        reasons.append("weak_company_name")
    else:
        score += 8
        reasons.append("clean_company_name")

    icp_score = int(row.get("icp_score") or 0)
    score += min(icp_score // 4, 20)
    if row.get("matched_terms"):
        reasons.append("icp_match")

    personalization = int(row.get("personalization_score") or 0)
    score += min(personalization // 5, 18)
    if personalization >= 75:
        reasons.append("strong_enrichment")

    contact_type = row.get("contact_type", "")
    contact_score = int(row.get("contact_score") or row.get("contact_confidence") or 0)
    score += min(contact_score // 5, 18)
    if contact_type:
        reasons.append(contact_type)

    if B2B_SIGNAL_RE.search(facts):
        score += 12
        reasons.append("b2b_signal")

    if NOISY_PRODUCT_RE.search(facts_lower):
        score -= 25
        reasons.append("noisy_product")

    if row.get("website_status") != "ok":
        score -= 15
        reasons.append("website_failed")

    return max(0, min(score, 100)), enricher.FACT_SEPARATOR.join(reasons)


def _name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    if local.lower() in ROLE_PREFIXES:
        return ""
    parts = re.split(r"[._+\-]+", local)
    return " ".join(p.capitalize() for p in parts if p and not p.isdigit())


def _valid_person_name(name: str) -> bool:
    value = _clean_text(name.replace("\n", " "))
    if not value or len(value) > 45:
        return False
    parts = value.split()
    if len(parts) < 2:
        return False
    if any(part in BAD_PERSON_WORDS for part in parts):
        return False
    if any(len(part) < 3 for part in parts[1:]):
        return False
    if not all(re.match(r"^[A-Z][a-z]+$", part) for part in parts):
        return False
    return True


def _person_from_text(text: str) -> tuple[str, str]:
    text = _clean_text(text)
    for pattern in (PERSON_HINT_RE, PERSON_REVERSE_HINT_RE):
        match = pattern.search(text or "")
        if not match:
            continue
        name = _clean_text(match.group("name"))
        role = _clean_text(match.group("role")).title()
        if _valid_person_name(name):
            return name, role
    return "", ""


def _has_contact_page(pages: list[enricher.PageContent]) -> str:
    for page in pages:
        if any(part in urlparse(page.url).path.lower() for part in ("contact", "team", "press")):
            return page.url
    return ""


def _email_rank(email: str, source_url: str) -> tuple[int, str]:
    local = email.split("@", 1)[0].lower()
    path = urlparse(source_url).path.lower()
    if local in ROLE_PREFIXES:
        role_rank = {
            "partnerships": 84,
            "partner": 82,
            "growth": 80,
            "marketing": 78,
            "product": 76,
            "sales": 74,
            "team": 62,
            "hello": 58,
            "hi": 55,
            "contact": 54,
            "founders": 46,
            "press": 42,
            "support": 35,
            "info": 30,
        }.get(local, 40)
        return role_rank, ""
    if PERSON_LOCAL_RE.match(local):
        # first@domain is useful, first.last@domain is better.
        rank = 95 if any(sep in local for sep in (".", "_", "-")) else 88
        if any(part in path for part in ("team", "about", "company")):
            rank += 3
        return rank, _name_from_email(email)
    return 50, _name_from_email(email)


def score_contact(contact: Contact) -> tuple[int, str]:
    """Score how useful a discovered contact is for practical outreach."""
    score = 0
    reasons = []
    role = contact.role or ""
    local = contact.email.split("@", 1)[0].lower() if contact.email else ""

    if contact.contact_type == "public_email":
        score += 72
        reasons.append("person_email")
        if contact.name:
            score += 10
            reasons.append("name_from_email")
    elif contact.contact_type == "role_inbox":
        if local in HIGH_VALUE_ROLE_PREFIXES:
            score += 74
            reasons.append("relevant_role_inbox")
        elif local in LOW_VALUE_ROLE_PREFIXES:
            score += 44
            reasons.append("generic_role_inbox")
        else:
            score += 50
            reasons.append("role_inbox")
    elif contact.contact_type == "linkedin_profile":
        if RELEVANT_ROLE_RE.search(role):
            score += 68
            reasons.append("linkedin_relevant_role")
        else:
            score += 55
            reasons.append("linkedin_profile")
    elif contact.contact_type == "public_person":
        if RELEVANT_ROLE_RE.search(role):
            score += 58
            reasons.append("relevant_public_person")
        elif EXEC_ROLE_RE.search(role):
            score += 30
            reasons.append("exec_public_person")
        else:
            score += 40
            reasons.append("public_person")
    elif contact.contact_type == "contact_page":
        score += 28
        reasons.append("contact_page")
    elif contact.contact_type == "role_guess":
        score += 18
        reasons.append("guessed_role_email")

    score += min(contact.confidence // 10, 10)
    if RELEVANT_ROLE_RE.search(role):
        score += 12
        reasons.append("role_relevance")
    if EXEC_ROLE_RE.search(role) and contact.contact_type != "public_email":
        score -= 10
        reasons.append("exec_only")

    return max(0, min(score, 100)), enricher.FACT_SEPARATOR.join(reasons)


def find_contact(pages: list[enricher.PageContent], domain: str, guess_role_email: bool = False) -> Contact:
    same_domain_emails = []
    public_person = Contact(contact_type="not_found", confidence=0)
    for page in pages:
        text = "\n".join([page.title, page.description, page.text])
        if not public_person.name:
            name, role = _person_from_text(text)
            if name:
                public_person = Contact(
                    name=name,
                    role=role,
                    contact_type="public_person",
                    confidence=55,
                    source_url=page.url,
                )
        for email in EMAIL_RE.findall(text):
            if normalize_domain(email.split("@", 1)[1]) == domain:
                same_domain_emails.append((email.lower(), page.url))

    seen = set()
    emails = []
    for email, url in same_domain_emails:
        if email not in seen:
            seen.add(email)
            emails.append((email, url))

    if emails:
        ranked = sorted(
            ((email, url, *_email_rank(email, url)) for email, url in emails),
            key=lambda item: item[2],
            reverse=True,
        )
        email, url, rank, name = ranked[0]
        local = email.split("@", 1)[0].lower()
        if local not in ROLE_PREFIXES:
            confidence = min(rank, 95)
            return Contact(
                name=name,
                email=email,
                contact_type="public_email",
                confidence=confidence,
                source_url=url,
            )
        # Skip useless inboxes (support@, contact@, info@, etc.) — treat as no contact
        if local in OUTREACH_USELESS_PREFIXES:
            # Try to find a useful role inbox instead
            for alt_email, alt_url, alt_rank, alt_name in ranked[1:]:
                alt_local = alt_email.split("@", 1)[0].lower()
                if alt_local not in ROLE_PREFIXES:
                    return Contact(
                        name=alt_name, email=alt_email,
                        contact_type="public_email",
                        confidence=min(alt_rank, 95), source_url=alt_url,
                    )
                if alt_local not in OUTREACH_USELESS_PREFIXES:
                    return Contact(
                        email=alt_email, contact_type="role_inbox",
                        confidence=alt_rank, source_url=alt_url,
                    )
            # All emails are useless — fall through to LinkedIn search
        else:
            return Contact(
                email=email,
                contact_type="role_inbox",
                confidence=rank,
                source_url=url,
            )

    contact_page = _has_contact_page(pages)
    if public_person.name:
        return public_person
    if guess_role_email:
        return Contact(
            name=public_person.name,
            role=public_person.role,
            email=f"{GUESSED_ROLE_EMAILS[0]}@{domain}",
            contact_type="role_guess",
            confidence=30,
            source_url=contact_page or public_person.source_url,
        )
    if contact_page:
        return Contact(
            contact_type="contact_page",
            confidence=35,
            source_url=contact_page,
        )

    return Contact(contact_type="not_found", confidence=0)


def discover_rows(
    sources: list[str],
    icp: str = "",
    limit: int = 10,
    require_contact: bool = False,
    max_pages: int = 3,
    workers: int = 8,
    source_limit: int = 25,
    guess_role_email: bool = False,
    progress_callback: object = None,
) -> list[dict]:
    """Discover leads from public source URLs.

    Args:
        progress_callback: Optional callable(processed, total, found, elapsed_seconds)
            called after each company is processed for live progress updates.
    """
    companies = discover_company_pool(sources, limit=limit, source_limit=source_limit, workers=workers)
    rows = []
    workers = _clamp_workers(workers)
    _discover_start = time.monotonic()
    _discover_processed = 0
    _discover_total = len(companies)

    def build_row(company: CandidateCompany) -> dict | None:
        pages = crawl_company_pages(company.website, max_pages=max_pages)
        pages = _merge_pages(pages, search_company_pages(company))
        facts = enricher.extract_facts(pages)
        warnings = enricher.quality_warnings(facts, pages)
        enrichment = {
            "website_status": "ok" if pages else "fetch_failed",
            "company_summary": enricher.summarize_facts(facts),
            "personalization_facts": enricher.facts_to_text(facts),
            "source_urls": enricher.source_urls(facts),
            "personalization_score": str(enricher.personalization_score(facts)),
            "quality_warnings": enricher.FACT_SEPARATOR.join(warnings),
        }
        contact = find_contact(pages, normalize_domain(company.website), guess_role_email=guess_role_email)
        # Check if this is a useless role inbox (support@, contact@, info@, etc.)
        _is_useless_inbox = (
            contact.contact_type == "role_inbox"
            and contact.email
            and contact.email.split("@", 1)[0].lower() in OUTREACH_USELESS_PREFIXES
        )
        # LinkedIn fallback for weak or useless contacts
        if contact.contact_type in ("public_person", "contact_page", "role_guess", "not_found") or _is_useless_inbox:
            linkedin_contacts = search_linkedin_contacts(company.company, normalize_domain(company.website))
            if linkedin_contacts:
                best = linkedin_contacts[0]
                # Always use LinkedIn profile URL — never guess first.last@ emails
                contact = Contact(
                    name=best.name,
                    role=best.role,
                    email=best.source_url,
                    contact_type="linkedin_profile",
                    confidence=best.confidence,
                    source_url=best.source_url,
                )
        contact_score, contact_score_reasons = score_contact(contact)
        # Drop garbage public_person contacts (regex-extracted names from page text)
        if contact.contact_type == "public_person":
            contact = Contact(contact_type="not_found", confidence=0)
        # Drop useless role inboxes — they are worthless for cold outreach
        if (contact.contact_type == "role_inbox" and contact.email
                and contact.email.split("@", 1)[0].lower() in OUTREACH_USELESS_PREFIXES):
            return None
        # Drop leads without a usable email — this is an outreach tool
        if not contact.email:
            return None
        icp_score, matched_terms = score_company(company, enrichment, icp)
        # Defensive: never let role prefixes leak into name fields
        if contact.email and "@" in contact.email:
            email_local = contact.email.split("@", 1)[0].lower()
            if email_local in ROLE_PREFIXES and not contact.name:
                contact = Contact(
                    email=contact.email,
                    contact_type=contact.contact_type,
                    confidence=contact.confidence,
                    source_url=contact.source_url,
                )
        name_parts = contact.name.split()
        row = {
            "email": contact.email,
            "first_name": name_parts[0] if name_parts else "",
            "last_name": " ".join(name_parts[1:]) if len(name_parts) > 1 else "",
            "company": company.company,
            "website": company.website,
            "discovery_source_url": company.discovery_source_url,
            "discovery_reason": company.discovery_reason,
            "icp_score": str(icp_score),
            "matched_terms": matched_terms,
            "contact_name": contact.name,
            "contact_role": contact.role,
            "contact_email": contact.email,
            "contact_type": contact.contact_type,
            "contact_confidence": str(contact.confidence),
            "contact_score": str(contact_score),
            "contact_score_reasons": contact_score_reasons,
            "contact_source_url": contact.source_url,
            **enrichment,
        }
        lead_score, lead_score_reasons = score_lead(row)
        row["lead_score"] = str(lead_score)
        row["lead_score_reasons"] = lead_score_reasons
        return row

    # Process companies in batches — keep going until we fill the requested limit
    processed_domains: set[str] = set()
    batch_start = 0
    batch_size = limit  # First batch tries exactly `limit` companies

    while len(rows) < limit and batch_start < len(companies):
        batch = []
        for company in companies[batch_start:]:
            domain = normalize_domain(company.website)
            if domain not in processed_domains:
                processed_domains.add(domain)
                batch.append(company)
            if len(batch) >= batch_size:
                break
        batch_start += batch_size

        if not batch:
            break

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_company = {executor.submit(build_row, company): company for company in batch}
            for future in as_completed(future_to_company):
                row = future.result()
                _discover_processed += 1
                if row is not None:
                    rows.append(row)
                if progress_callback is not None:
                    try:
                        elapsed = time.monotonic() - _discover_start
                        progress_callback(_discover_processed, _discover_total, len(rows), elapsed)
                    except Exception:
                        pass

        # After first batch, process remaining companies in smaller batches
        batch_size = max(limit - len(rows), 2)

    rows.sort(
        key=lambda r: (
            int(r.get("lead_score", "0")),
            int(r.get("contact_score", "0")),
            int(r.get("icp_score", "0")),
            int(r.get("personalization_score", "0")),
        ),
        reverse=True,
    )
    return rows[:limit]


def write_csv(rows: list[dict], output: str) -> None:
    fieldnames = [
        "email", "first_name", "last_name", "company", "website",
        "discovery_source_url", "discovery_reason", "lead_score", "lead_score_reasons",
        "icp_score", "matched_terms",
        "contact_name", "contact_role", "contact_email", "contact_type",
        "contact_confidence", "contact_score", "contact_score_reasons",
        "contact_source_url", "website_status",
        "company_summary", "personalization_facts", "source_urls",
        "personalization_score", "quality_warnings",
    ]
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ===========================================================================
# Company-first discovery: ICP + region -> ranked company list with a durable
# contact bundle (company email, phone, address, company LinkedIn). Replaces the
# brittle person-finder as the default. Person discovery is available opt-in.
# ===========================================================================

_LINKEDIN_COMPANY_RE = re.compile(
    r"https?://[a-z]{0,3}\.?linkedin\.com/company/[A-Za-z0-9_%.\-]+", re.IGNORECASE
)
# Conservative phone matcher — international-ish, avoids matching long ID strings.
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-]{6,16}\d)(?!\w)")

PARTNERSHIP_PATH_HINTS = (
    "partners", "partner", "partnership", "partnerships",
    "become-a-partner", "reseller", "resellers", "affiliate", "affiliates",
)

# Company-level email policy (the inverse of the person-finder): generic inboxes
# like info@/contact@ are KEPT — they are a legitimate first touch for partnership
# outreach. Partnership/BD inboxes rank highest.
COMPANY_EMAIL_PRIORITY = {
    "partnerships": 95, "partner": 93, "bd": 90, "business-development": 90,
    "growth": 86, "marketing": 84, "sales": 82, "hello": 70, "contact": 66,
    "info": 64, "enquiries": 62, "enquiry": 62, "team": 60, "press": 50,
    "media": 48, "support": 40,
}

_SOCIAL_HOSTS = (
    "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "youtube.com",
)

# Region hint maps — keyed by a CANONICAL region name. Freeform user input
# ("United Kingdom (UK)", "uk", "England") is resolved to a canonical key via
# _resolve_region_key before lookup, so the signals actually fire regardless of
# how the region was phrased. Easily extensible.
_REGION_CCTLD = {
    "bangladesh": "bd", "india": "in", "pakistan": "pk", "turkey": "tr",
    "germany": "de", "france": "fr", "united kingdom": "uk", "united states": "us",
    "nigeria": "ng", "kenya": "ke", "indonesia": "id", "brazil": "br", "mexico": "mx",
}
_REGION_PHONE = {
    "bangladesh": "+880", "india": "+91", "pakistan": "+92", "turkey": "+90",
    "germany": "+49", "france": "+33", "united kingdom": "+44", "united states": "+1",
    "nigeria": "+234", "kenya": "+254", "indonesia": "+62", "brazil": "+55", "mexico": "+52",
}
_REGION_CITIES = {
    "bangladesh": ["dhaka", "chattogram", "chittagong", "khulna", "sylhet", "rajshahi"],
    "united kingdom": [
        "london", "manchester", "birmingham", "leeds", "glasgow", "edinburgh",
        "bristol", "liverpool", "sheffield", "surrey", "england", "scotland", "wales",
    ],
    "united states": ["new york", "san francisco", "los angeles", "chicago", "boston", "austin", "seattle"],
    "germany": ["berlin", "munich", "hamburg", "frankfurt", "cologne"],
    "france": ["paris", "lyon", "marseille", "toulouse"],
    "india": ["mumbai", "delhi", "bengaluru", "bangalore", "hyderabad", "chennai", "pune"],
}

# Freeform aliases -> canonical region key. Short aliases (<=3 chars) are matched
# on word boundaries; longer ones as substrings (longest first).
_REGION_ALIASES = {
    "united kingdom": "united kingdom", "great britain": "united kingdom",
    "britain": "united kingdom", "england": "united kingdom", "scotland": "united kingdom",
    "wales": "united kingdom", "uk": "united kingdom", "gb": "united kingdom",
    "united states": "united states", "america": "united states", "usa": "united states",
    "us": "united states",
    "bangladesh": "bangladesh", "india": "india", "pakistan": "pakistan",
    "turkey": "turkey", "türkiye": "turkey", "turkiye": "turkey",
    "germany": "germany", "deutschland": "germany", "france": "france",
    "nigeria": "nigeria", "kenya": "kenya", "indonesia": "indonesia",
    "brazil": "brazil", "brasil": "brazil", "mexico": "mexico", "méxico": "mexico",
}


def _resolve_region_key(region: str) -> str | None:
    """Map a freeform region string to a canonical key (longest alias wins)."""
    r = (region or "").lower()
    for alias in sorted(_REGION_ALIASES, key=len, reverse=True):
        if len(alias) <= 3:
            if re.search(r"\b" + re.escape(alias) + r"\b", r):
                return _REGION_ALIASES[alias]
        elif alias in r:
            return _REGION_ALIASES[alias]
    return None

_SIZE_BAND_RE = re.compile(r"(\d[\d,\.]*)\s*\+?\s*(?:employees|staff|people|team members)", re.IGNORECASE)
_SME_HINT_RE = re.compile(
    r"\b(family[- ]owned|family business|since \d{4}|founded in \d{4}|small team|boutique)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Front-end: candidate companies from LLM seed + search (sources optional)
# ---------------------------------------------------------------------------

def _resolve_llm_provider() -> dict | None:
    """Resolve an LLM provider config for discovery seeding, or None if unavailable.

    Mirrors the resolution order used by the email run path: default provider ->
    its config -> any usable LLM provider -> legacy anthropic key. Returns None
    when nothing is set up so callers degrade gracefully to search-only discovery.
    """
    try:
        from opencold import config, generator as _gen
    except Exception:
        return None
    try:
        providers = config.get_providers()
        name = config.get_default_provider_name()
        prov = providers.get(name) if name else None
        if prov and prov.get("type") in ("anthropic", "openai", "proxy") and prov.get("api_key"):
            return prov
        for candidate in providers.values():
            if candidate.get("type") in ("anthropic", "openai", "proxy") and candidate.get("api_key"):
                return candidate
        legacy = config.get_api_key("anthropic")
        if legacy:
            return {"type": "anthropic", "api_key": legacy, "default_model": _gen.DEFAULT_MODEL}
    except Exception:
        return None
    return None


_SEED_SYSTEM = (
    "You are a B2B market researcher. You output ONLY compact JSON, no prose, no "
    "markdown code fences. You never invent fake companies; if unsure, return fewer."
)


def _build_seed_prompt(icp: str, region: str, count: int) -> str:
    return (
        f"Target profile: {icp}\n"
        f"Region/country: {region}\n\n"
        f"Return up to {count} real, currently-operating companies that match the "
        f"target profile and are based in or serve that region. Prefer local small "
        f"and mid-size companies over global multinationals.\n"
        f"Also list authoritative local indexes where many more such companies are "
        f"registered (industry regulator, licensing body, trade association, chamber "
        f"of commerce) — these are used as extra search hints.\n\n"
        f'Output JSON exactly: {{"companies": ["Company Name", ...], '
        f'"local_directories": ["regulator/association name or url", ...]}}'
    )


def _parse_json_object(text: str) -> dict:
    """Best-effort parse of a JSON object from an LLM response (tolerates fences/prose)."""
    if not text:
        return {}
    cleaned = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


def seed_companies_via_llm(
    icp: str, region: str, count: int = 30, provider_config: dict | None = None
) -> dict:
    """Ask an LLM for known companies + local directories for (ICP, region).

    Returns {"companies": [...], "local_directories": [...]}. On any failure or
    when no provider is available, returns empty lists so discovery degrades to
    search-only.
    """
    prov = provider_config or _resolve_llm_provider()
    if not prov:
        return {"companies": [], "local_directories": []}
    try:
        from opencold import generator as _gen
        raw = _gen.complete(prov, _SEED_SYSTEM, _build_seed_prompt(icp, region, count), max_tokens=1024)
    except Exception:
        return {"companies": [], "local_directories": []}
    data = _parse_json_object(raw)
    companies = [c.strip() for c in data.get("companies", []) if isinstance(c, str) and c.strip()]
    directories = [d.strip() for d in data.get("local_directories", []) if isinstance(d, str) and d.strip()]
    seen: set[str] = set()
    uniq: list[str] = []
    for c in companies:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return {"companies": uniq[:count], "local_directories": directories[:10]}


def region_query_templates(icp: str, region: str) -> list[str]:
    icp = (icp or "").strip()
    region = (region or "").strip()
    templates = [
        f"{icp} companies in {region}",
        f"list of {icp} in {region}",
        f"top {icp} {region}",
        f"{icp} {region} contact email",
        f"{icp} association {region} members",
    ]
    return [q for q in templates if q.strip()]


def _candidate_from_result(result: SearchResult, reason: str) -> CandidateCompany | None:
    parsed = urlparse(result.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if _is_blocked_host(parsed.netloc):
        return None
    domain = normalize_domain(result.url)
    if not domain or _is_blocked_domain(domain) or _is_directory_domain(domain):
        return None
    return CandidateCompany(
        company=_company_from_domain(domain),
        website=f"https://{domain}",
        discovery_source_url=result.url,
        discovery_reason=reason,
    )


def discover_companies_by_query(
    icp: str, region: str, limit: int = 50, extra_queries: list[str] | None = None
) -> list[CandidateCompany]:
    queries = region_query_templates(icp, region) + list(extra_queries or [])
    candidates: dict[str, CandidateCompany] = {}
    for query in queries:
        for result in web_search(query, num=10):
            cand = _candidate_from_result(result, f"search: {query}")
            if not cand:
                continue
            candidates.setdefault(normalize_domain(cand.website), cand)
            if len(candidates) >= limit:
                return list(candidates.values())
    return list(candidates.values())


def discover_company_candidates(
    icp: str,
    region: str,
    sources: list[str] | None = None,
    limit: int = 50,
    workers: int = 8,
    use_llm: bool = True,
    seed_count: int = 30,
) -> list[CandidateCompany]:
    """Collect candidate companies from LLM seeding (A), search harvest (B), and
    an optional manual sources file (C). Deduped by registrable domain; first
    channel to surface a domain wins and tags it."""
    candidates: dict[str, CandidateCompany] = {}

    def _add(cand: CandidateCompany, channel: str) -> None:
        domain = normalize_domain(cand.website)
        if not domain or domain in candidates:
            return
        cand.discovery_channel = channel
        candidates[domain] = cand

    extra_queries: list[str] = []

    # Channel A: LLM seed (names -> websites) — only when a provider is configured.
    if use_llm:
        prov = _resolve_llm_provider()
        if prov:
            seed = seed_companies_via_llm(icp, region, count=seed_count, provider_config=prov)
            extra_queries = [f"{d} {region}" for d in seed.get("local_directories", [])]
            names = seed.get("companies", [])
            if names:
                # Disambiguate namesakes at the source: search with ICP+region
                # context and prefer the target country's ccTLD.
                context = f"{icp} {region}".strip()
                prefer_cc = _REGION_CCTLD.get(_resolve_region_key(region) or "")
                worker_n = max(1, min(_clamp_workers(workers), len(names)))
                with ThreadPoolExecutor(max_workers=worker_n) as executor:
                    future_to_name = {
                        executor.submit(
                            resolve_company_website, n,
                            require_match=True, context=context, prefer_cc=prefer_cc,
                        ): n
                        for n in names
                    }
                    for future in as_completed(future_to_name):
                        name = future_to_name[future]
                        try:
                            url = future.result()
                        except Exception:
                            url = None
                        if not url:
                            continue
                        _add(CandidateCompany(
                            company=name,
                            website=url,
                            discovery_source_url=url,
                            discovery_reason=f"llm seed: {icp} in {region}",
                        ), "llm")

    # Channel B: search harvest (always runs).
    for cand in discover_companies_by_query(icp, region, limit=limit, extra_queries=extra_queries):
        _add(cand, "search")

    # Channel C: optional manual sources (back-compat power-user channel).
    if sources:
        for cand in discover_company_pool(sources, limit=limit, workers=workers):
            _add(cand, "sources")

    return list(candidates.values())[:max(limit, 1)]


# ---------------------------------------------------------------------------
# Back-end: structured-data-first contact extraction
# ---------------------------------------------------------------------------

@dataclass
class CompanyContacts:
    emails: list = field(default_factory=list)   # list[tuple[email, source_url]]
    phones: list = field(default_factory=list)
    socials: list = field(default_factory=list)
    address: str = ""
    linkedin_company_url: str = ""
    partnership_url: str = ""
    company_name: str = ""


_CONTACT_PATHS = ("", "/contact", "/contact-us", "/about", "/about-us", "/imprint", "/legal", "/company")


def _clean_phone(raw: str) -> str:
    cleaned = re.sub(r"[^\d+]", "", (raw or "").strip())
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 7 or len(digits) > 15:
        return ""
    return cleaned


def _register_social(contacts: CompanyContacts, url: str) -> None:
    if not url or not isinstance(url, str):
        return
    low = url.lower()
    if "linkedin.com/company/" in low:
        match = _LINKEDIN_COMPANY_RE.search(url)
        clean = (match.group(0) if match else url).split("?")[0]
        if not contacts.linkedin_company_url:
            contacts.linkedin_company_url = clean
        if clean not in contacts.socials:
            contacts.socials.append(clean)
        return
    for host in _SOCIAL_HOSTS:
        if host in low:
            clean = url.split("?")[0]
            if clean not in contacts.socials:
                contacts.socials.append(clean)
            break


def _extract_jsonld_org(soup: BeautifulSoup) -> dict:
    """Pull contact fields from JSON-LD Organization/LocalBusiness blocks."""
    out = {"email": "", "telephone": "", "address": "", "sameAs": [], "name": ""}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        flat = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                flat.extend(item["@graph"])
            else:
                flat.append(item)
        for item in flat:
            if not isinstance(item, dict):
                continue
            if not out["name"] and isinstance(item.get("name"), str):
                out["name"] = item["name"].strip()
            if not out["email"]:
                email = item.get("email", "")
                if isinstance(email, str) and "@" in email:
                    out["email"] = email.replace("mailto:", "").strip()
            if not out["telephone"]:
                tel = item.get("telephone", "")
                if isinstance(tel, str) and tel.strip():
                    out["telephone"] = tel.strip()
            same_as = item.get("sameAs", [])
            if isinstance(same_as, str):
                same_as = [same_as]
            if isinstance(same_as, list):
                out["sameAs"].extend([s for s in same_as if isinstance(s, str)])
            if not out["address"]:
                addr = item.get("address")
                if isinstance(addr, dict):
                    parts = [str(addr.get(k, "")) for k in
                             ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
                    out["address"] = ", ".join(p for p in parts if p and p != "None").strip(", ")
                elif isinstance(addr, str) and addr.strip():
                    out["address"] = addr.strip()
    return out


def extract_company_contacts(website: str, max_pages: int = 5) -> CompanyContacts:
    """Extract a durable company contact bundle, structured-data first.

    Parses JSON-LD Organization/LocalBusiness (email/telephone/address/sameAs),
    mailto:/tel: anchors, and footer social links across a few high-value pages.
    Regex email/phone extraction is used only as a fallback when nothing
    structured is found.
    """
    contacts = CompanyContacts()
    base = enricher.normalize_url(website)
    if not base:
        return contacts
    parsed = urlparse(base)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    domain = normalize_domain(website)
    seen_emails: set[str] = set()
    seen_phones: set[str] = set()
    home_text = ""

    for path in _CONTACT_PATHS[:max_pages]:
        url = origin if not path else urljoin(origin, path)
        html = enricher._fetch_html(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        if not path:
            home_text = soup.get_text(" ", strip=True)

        org = _extract_jsonld_org(soup)
        if org["name"] and not contacts.company_name:
            contacts.company_name = org["name"]
        if org["email"] and org["email"].lower() not in seen_emails:
            seen_emails.add(org["email"].lower())
            contacts.emails.append((org["email"].lower(), url))
        if org["telephone"]:
            tel = _clean_phone(org["telephone"])
            if tel and tel not in seen_phones:
                seen_phones.add(tel)
                contacts.phones.append(tel)
        if org["address"] and not contacts.address:
            contacts.address = org["address"]
        for same in org["sameAs"]:
            _register_social(contacts, same)

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            low = href.lower()
            if low.startswith("mailto:"):
                email = href[7:].split("?")[0].strip().lower()
                if "@" in email and email not in seen_emails:
                    seen_emails.add(email)
                    contacts.emails.append((email, url))
            elif low.startswith("tel:"):
                tel = _clean_phone(href[4:])
                if tel and tel not in seen_phones:
                    seen_phones.add(tel)
                    contacts.phones.append(tel)
            else:
                _register_social(contacts, urljoin(url, href))
                if not contacts.partnership_url and any(
                    f"/{hint}" in low or low.rstrip("/").endswith(hint)
                    for hint in PARTNERSHIP_PATH_HINTS
                ):
                    full = urljoin(url, href).split("#")[0]
                    if normalize_domain(full) == domain:
                        contacts.partnership_url = full

        # Regex email fallback only when nothing on-domain found yet.
        if not contacts.emails:
            for email in EMAIL_RE.findall(soup.get_text(" ", strip=True)):
                el = email.lower()
                if "@" in el and normalize_domain(el.split("@", 1)[1]) == domain and el not in seen_emails:
                    seen_emails.add(el)
                    contacts.emails.append((el, url))

    # Phone regex fallback from the home page text.
    if not contacts.phones and home_text:
        match = _PHONE_RE.search(home_text)
        if match:
            tel = _clean_phone(match.group(1))
            if tel:
                contacts.phones.append(tel)

    return contacts


def pick_company_email(emails: list, domain: str) -> tuple[str, str, str]:
    """Choose the best company email. Returns (email, email_type, source_url).

    Company policy keeps generic inboxes (info@/contact@) — legitimate first
    touch for partnership outreach — and ranks partnership/BD inboxes highest. A
    named-person email outranks all role inboxes. On-domain emails are preferred.
    """
    best: tuple[int, str, str, str] | None = None
    for email, url in emails:
        if "@" not in email:
            continue
        local, email_host = email.split("@", 1)
        local = local.lower()
        on_domain = normalize_domain(email_host) == domain
        if local in COMPANY_EMAIL_PRIORITY or local in ROLE_PREFIXES:
            rank = COMPANY_EMAIL_PRIORITY.get(local, 45)
            etype = "role_inbox"
        elif PERSON_LOCAL_RE.match(local):
            rank = 98 if any(sep in local for sep in (".", "_", "-")) else 92
            etype = "person_email"
        else:
            rank, etype = 55, "company_email"
        if not on_domain:
            # Penalize off-domain emails enough that any on-domain inbox wins, but
            # a sole freemail address (common for local SMEs) is still returned.
            rank -= 35
        if best is None or rank > best[0]:
            best = (rank, email, etype, url)
    if not best:
        return "", "", ""
    return best[1], best[2], best[3]


def find_company_linkedin(company: str, contacts: CompanyContacts, domain: str) -> str:
    if contacts.linkedin_company_url:
        return contacts.linkedin_company_url
    try:
        for result in web_search(f'"{company}" site:linkedin.com/company', num=5):
            match = _LINKEDIN_COMPANY_RE.search(result.url)
            if match:
                return match.group(0).split("?")[0]
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Value-add signals: region fit + coarse size tier
# ---------------------------------------------------------------------------

def region_fit(contacts: CompanyContacts, website: str, region: str, pages_text: str = "") -> tuple[int, str]:
    """Score how strongly a company is anchored in the target region (0-100).

    Cheap deterministic signals: ccTLD, phone country code, address/text mentions
    of the region or its major cities. Lets genuine locals outrank a multinational's
    localized page.
    """
    if not (region or "").strip():
        return 0, ""
    region_key = _resolve_region_key(region)
    score = 0
    reasons: list[str] = []
    domain = normalize_domain(website)
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    target_cc = _REGION_CCTLD.get(region_key) if region_key else None
    target_code = _REGION_PHONE.get(region_key) if region_key else None
    phones_joined = "".join(contacts.phones).replace(" ", "")

    if target_cc and (domain.endswith("." + target_cc) or tld == target_cc):
        score += 40
        reasons.append(f"cctld:.{target_cc}")
    if target_code and target_code in phones_joined:
        score += 35
        reasons.append(f"phone:{target_code}")
    haystack = (contacts.address + " " + pages_text).lower()
    tokens = [region_key or region.lower()] + (_REGION_CITIES.get(region_key, []) if region_key else [])
    if any(tok and tok in haystack for tok in tokens):
        score += 25
        reasons.append("addr_region_match")

    # Conflict: a clearly different known country (a wrong-country namesake).
    # Only checked against regions we have signals for, to avoid false flags.
    conflict = ""
    if target_cc:
        for cc in set(_REGION_CCTLD.values()):
            if cc != target_cc and (tld == cc or domain.endswith("." + cc)):
                conflict = f".{cc}"
                break
    if not conflict and target_code and score == 0:
        for code in set(_REGION_PHONE.values()):
            if code != target_code and phones_joined.startswith(code):
                conflict = code
                break
    if conflict:
        reasons.append(f"region_conflict:{conflict}")

    return min(score, 100), enricher.FACT_SEPARATOR.join(reasons)


def size_tier(pages_text: str, contacts: CompanyContacts) -> str:
    """Coarse company-size band (micro|sme|mid|enterprise) from cheap signals.

    Best-effort — emitted as a filter column, not a hard gate."""
    text = pages_text or ""
    match = _SIZE_BAND_RE.search(text)
    if match:
        try:
            n = int(re.sub(r"\D", "", match.group(1)))
            if n >= 1000:
                return "enterprise"
            if n >= 200:
                return "mid"
            if n >= 20:
                return "sme"
            return "micro"
        except ValueError:
            pass
    if _SME_HINT_RE.search(text):
        return "sme"
    return ""


# ---------------------------------------------------------------------------
# Verification: LLM judge (grounded) + deterministic gate
# ---------------------------------------------------------------------------

def _country_matches(region: str, country: str) -> bool:
    """True when a detected country resolves to the same canonical region."""
    if not country:
        return False
    rk = _resolve_region_key(region)
    ck = _resolve_region_key(country)
    return bool(rk and ck and rk == ck)


_JUDGE_SYSTEM = (
    "You verify whether companies match a target profile and region, using ONLY "
    "the provided website summary as evidence. You output compact JSON, no prose, "
    "no markdown fences. If a summary does not clearly establish a company's "
    "industry or country, you answer \"unknown\" — you never guess from the name."
)


def _build_judge_prompt(items: list[dict], icp: str, region: str) -> str:
    lines = [
        f"Target industry/profile: {icp}",
        f"Target region: {region}",
        "",
        "For each company, judge from its OWN website summary whether it matches the "
        "target industry AND is based in or serves the target region.",
        'Reply JSON: {"results":[{"i":0,"match":"yes|no|unknown","industry":"...",'
        '"country":"...","evidence":"<short quote from the summary>"}]}',
        "Rules: base every field ONLY on the summary text. If the summary is too "
        "thin to tell, use \"unknown\" (do not guess). Quote real words from the "
        "summary as evidence.",
        "",
        "Companies:",
    ]
    for it in items:
        summary = (it.get("summary") or "")[:500].replace("\n", " ")
        lines.append(f'[{it["i"]}] name="{it["name"]}" site={it["domain"]} summary="{summary}"')
    return "\n".join(lines)


def judge_companies(rows: list[dict], icp: str, region: str, provider_config: dict) -> dict:
    """Single batched LLM verdict per company, grounded in crawled summaries.

    Returns {row_index: {"match": yes|no|unknown, "industry", "country", "evidence"}}.
    On any failure returns {} so the caller falls back to deterministic signals.
    """
    items = []
    for idx, row in enumerate(rows):
        summary = " ".join([
            row.get("company_summary", ""), row.get("personalization_facts", ""),
        ]).strip()
        items.append({
            "i": idx,
            "name": row.get("company", ""),
            "domain": normalize_domain(row.get("website", "")),
            "summary": summary,
        })
    if not items:
        return {}
    try:
        from opencold import generator as _gen
        raw = _gen.complete(provider_config, _JUDGE_SYSTEM, _build_judge_prompt(items, icp, region), max_tokens=1500)
    except Exception:
        return {}
    data = _parse_json_object(raw)
    out: dict = {}
    for res in data.get("results", []):
        if isinstance(res, dict) and isinstance(res.get("i"), int):
            out[res["i"]] = {
                "match": str(res.get("match", "unknown")).lower().strip(),
                "industry": str(res.get("industry", "")),
                "country": str(res.get("country", "")),
                "evidence": str(res.get("evidence", "")),
            }
    return out


def _classify_company(row: dict, icp_evidence: bool, region_conflict: bool, llm: dict | None) -> tuple[str, str]:
    """Combine deterministic evidence with the (optional) LLM verdict.

    Authority split: deterministic signals own REGION (ccTLD/phone are hard facts
    the model can't override); the LLM owns INDUSTRY semantics. The model deferring
    ("unknown") never rejects — we fall back to deterministic. Disagreements land in
    'review', not silently trusted. Returns (confidence, reason).
    """
    region_fit_score = int(row.get("region_fit") or 0)
    llm = llm or {}
    llm_match = llm.get("match", "unknown")

    if region_conflict:
        return "rejected", "region_conflict"
    if llm_match == "no":
        detail = llm.get("industry") or llm.get("country") or "different company"
        return "rejected", f"llm_mismatch:{detail}"

    industry_ok = icp_evidence or llm_match == "yes"
    region_ok = region_fit_score > 0 or _country_matches(row.get("country", ""), llm.get("country", ""))

    if industry_ok and region_ok:
        suffix = "+llm" if llm_match == "yes" else ""
        return "verified", f"icp+region_confirmed{suffix}"
    if not industry_ok:
        return "review", "icp_unconfirmed"
    return "review", "region_unconfirmed"


# ---------------------------------------------------------------------------
# Orchestrator + CSV writer
# ---------------------------------------------------------------------------

COMPANY_CSV_FIELDS = [
    "email", "name", "company", "website",
    "match_confidence", "verification",
    "country", "region_fit", "company_email", "email_type", "phone", "address",
    "linkedin_company_url", "partnership_channel", "size_tier",
    "icp_score", "matched_terms",
    "website_status", "company_summary", "personalization_facts", "source_urls",
    "personalization_score",
    "discovery_channel", "discovery_source_url", "discovered_at",
    "lead_score", "lead_score_reasons", "quality_warnings",
]
COMPANY_PEOPLE_FIELDS = ["contact_name", "contact_role", "contact_linkedin", "contact_stale_warning"]

# Banner drawn in the CSV between verified Top-N and the review pile below.
WALL_BANNER = "═════ REVIEW BELOW — ICP/region NOT verified ═════"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _score_company_lead(
    row: dict,
    region_fit_score: int,
    email_type: str,
    region_targeted: bool = False,
    region_conflict: bool = False,
) -> tuple[int, str]:
    score = 30
    reasons: list[str] = []
    if row.get("website_status") == "ok":
        score += 10
        reasons.append("site_ok")
    else:
        score -= 15
        reasons.append("site_failed")
    score += min(int(row.get("icp_score") or 0) // 4, 20)
    if row.get("matched_terms"):
        reasons.append("icp_match")
    score += min(int(row.get("personalization_score") or 0) // 6, 15)
    if email_type == "person_email":
        score += 18
        reasons.append("person_email")
    elif email_type == "role_inbox":
        score += 12
        reasons.append("role_inbox")
    elif email_type == "company_email":
        score += 8
        reasons.append("company_email")
    if row.get("phone"):
        score += 5
        reasons.append("phone")
    if row.get("linkedin_company_url"):
        score += 6
        reasons.append("linkedin_company")
    if row.get("partnership_channel"):
        score += 8
        reasons.append("partnership_channel")
    score += min(region_fit_score // 5, 18)
    if region_fit_score >= 40:
        reasons.append("region_fit")
    # For a region-targeted search, sink wrong-country namesakes and softly
    # de-rank companies we couldn't confirm are in-region.
    if region_conflict:
        score -= 30
        reasons.append("region_conflict")
    elif region_targeted and region_fit_score == 0:
        score -= 15
        reasons.append("region_unconfirmed")
    if B2B_SIGNAL_RE.search(" ".join([row.get("company_summary", ""), row.get("personalization_facts", "")])):
        score += 6
        reasons.append("b2b_signal")
    return max(0, min(score, 100)), enricher.FACT_SEPARATOR.join(reasons)


def build_company_row(
    company: CandidateCompany,
    icp: str,
    region: str,
    max_pages: int = 4,
    find_people: bool = False,
) -> dict | None:
    domain = normalize_domain(company.website)
    pages = crawl_company_pages(company.website, max_pages=max_pages)
    pages = _merge_pages(pages, search_company_pages(company))
    facts = enricher.extract_facts(pages)
    enrichment = {
        "website_status": "ok" if pages else "fetch_failed",
        "company_summary": enricher.summarize_facts(facts),
        "personalization_facts": enricher.facts_to_text(facts),
        "source_urls": enricher.source_urls(facts),
        "personalization_score": str(enricher.personalization_score(facts)),
        "quality_warnings": enricher.FACT_SEPARATOR.join(enricher.quality_warnings(facts, pages)),
    }
    pages_text = " ".join(f"{p.title} {p.description} {p.text}" for p in pages)

    contacts = extract_company_contacts(company.website, max_pages=max_pages)
    name = company.company
    if contacts.company_name and (not name or name == _company_from_domain(domain)):
        name = contacts.company_name

    email, email_type, _email_src = pick_company_email(contacts.emails, domain)
    linkedin = find_company_linkedin(name, contacts, domain)
    rfit, rfit_reasons = region_fit(contacts, company.website, region, pages_text)
    region_conflict = "region_conflict" in rfit_reasons
    tier = size_tier(pages_text, contacts)

    if contacts.partnership_url:
        partnership = f"page:{contacts.partnership_url}"
    elif email and email.split("@", 1)[0].lower() in ("partnerships", "partner", "bd"):
        partnership = f"email:{email}"
    else:
        partnership = ""

    icp_score, matched_terms = score_company(company, enrichment, icp)
    if rfit_reasons:
        matched_terms = (matched_terms + (enricher.FACT_SEPARATOR if matched_terms else "") + rfit_reasons)

    row = {
        "email": email,
        "name": "",
        "company": name,
        "website": company.website,
        "country": region,
        "region_fit": str(rfit),
        "company_email": email,
        "email_type": email_type,
        "phone": contacts.phones[0] if contacts.phones else "",
        "address": contacts.address,
        "linkedin_company_url": linkedin,
        "partnership_channel": partnership,
        "size_tier": tier,
        "icp_score": str(icp_score),
        "matched_terms": matched_terms,
        "discovery_channel": getattr(company, "discovery_channel", "") or "",
        "discovery_source_url": company.discovery_source_url,
        "discovered_at": _now_iso(),
        **enrichment,
    }
    lead_score, lead_reasons = _score_company_lead(
        row, rfit, email_type,
        region_targeted=bool(region), region_conflict=region_conflict,
    )
    row["lead_score"] = str(lead_score)
    row["lead_score_reasons"] = lead_reasons
    # Carried for verification/classification; underscore keys are not written to
    # CSV (DictWriter uses fixed fieldnames + extrasaction="ignore").
    row["_icp_evidence"] = _icp_evidence(icp, enrichment)
    row["_region_conflict"] = region_conflict

    if find_people:
        people = search_linkedin_contacts(name, domain)
        best = people[0] if people else None
        row["contact_name"] = best.name if best else ""
        row["contact_role"] = best.role if best else ""
        row["contact_linkedin"] = best.source_url if best else ""
        row["contact_stale_warning"] = "person_company_mapping_may_be_stale" if best else ""
    return row


def discover_company_rows(
    icp: str,
    region: str,
    sources: list[str] | None = None,
    limit: int = 30,
    workers: int = 8,
    max_pages: int = 4,
    use_llm: bool = True,
    seed_count: int = 30,
    find_people: bool = False,
    progress_callback: object = None,
) -> list[dict]:
    """Discover companies for (ICP, region) with a durable contact bundle.

    Builds a candidate pool, then verifies each lead against ICP + region using
    deterministic evidence and (when a provider is configured) a single batched
    LLM judge. Returns verified leads first (up to `limit`) followed by the
    review/rejected pile, each row tagged with match_confidence/verification.

    Args:
        progress_callback: Optional callable(processed, total, found, elapsed_seconds).
    """
    # Crawl more than `limit` so rejected namesakes can be replaced by verified
    # ones — but cap the pool so latency stays bounded.
    pool = min(max(limit * 2, limit + 8), 40)
    candidates = discover_company_candidates(
        icp, region, sources=sources, limit=pool,
        workers=workers, use_llm=use_llm, seed_count=seed_count,
    )
    # Dedupe by domain up front (channels already dedupe, but be safe).
    seen: set[str] = set()
    deduped: list[CandidateCompany] = []
    for cand in candidates:
        domain = normalize_domain(cand.website)
        if domain and domain not in seen:
            seen.add(domain)
            deduped.append(cand)
    candidates = deduped[:pool]

    rows: list[dict] = []
    workers = _clamp_workers(workers)
    start = time.monotonic()
    processed = 0
    total = len(candidates)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_company = {
            executor.submit(build_company_row, company, icp, region, max_pages, find_people): company
            for company in candidates
        }
        for future in as_completed(future_to_company):
            processed += 1
            try:
                row = future.result()
            except Exception:
                row = None
            if row is not None:
                rows.append(row)
            if progress_callback is not None:
                try:
                    progress_callback(processed, total, len(rows), time.monotonic() - start)
                except Exception:
                    pass

    # Single batched LLM judge over all built rows, if a provider is available.
    verdicts: dict = {}
    if use_llm and rows:
        prov = _resolve_llm_provider()
        if prov:
            verdicts = judge_companies(rows, icp, region, prov)

    # Classify each row, then rank within its confidence band by lead score.
    for idx, row in enumerate(rows):
        confidence, why = _classify_company(
            row, bool(row.get("_icp_evidence")), bool(row.get("_region_conflict")), verdicts.get(idx),
        )
        row["match_confidence"] = confidence
        row["verification"] = why

    def _rank(row: dict) -> int:
        return int(row.get("lead_score", "0"))

    verified = sorted((r for r in rows if r["match_confidence"] == "verified"), key=_rank, reverse=True)
    review = sorted((r for r in rows if r["match_confidence"] == "review"), key=_rank, reverse=True)
    rejected = sorted((r for r in rows if r["match_confidence"] == "rejected"), key=_rank, reverse=True)

    # Verified fill the Top-N; the review/rejected pile (capped) goes below the wall.
    return verified[:limit] + (review + rejected)[:limit]


def write_company_csv(rows: list[dict], output: str) -> None:
    """Write company leads; draws a visual wall between verified and the rest.

    Verified rows are written first, then a blank gap row and a banner divider,
    then the review/rejected rows — so opened in a spreadsheet the genuinely
    verified Top-N sit clearly above the pile that needs review.
    """
    fieldnames = list(COMPANY_CSV_FIELDS)
    if rows and any("contact_name" in r for r in rows):
        fieldnames += COMPANY_PEOPLE_FIELDS
    has_verified = any(r.get("match_confidence") == "verified" for r in rows)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        wall_drawn = False
        for row in rows:
            if (not wall_drawn and has_verified
                    and row.get("match_confidence") not in ("verified", "", None)):
                writer.writerow({})  # blank gap row
                writer.writerow({"company": WALL_BANNER})
                wall_drawn = True
            writer.writerow(row)
