"""Company name to website resolution."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from opencold.discovery_data import COMPANY_SUFFIXES_RE
from opencold.discovery_domains import _is_blocked_domain, _is_blocked_host, normalize_domain
from opencold.discovery_search import web_search
from opencold.textnorm import fold

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
    cleaned = fold(COMPANY_SUFFIXES_RE.sub("", company or "").strip())
    return [t for t in re.split(r"[^a-z0-9]+", cleaned) if len(t) >= 2]


def _domain_matches_company(domain: str, tokens: list[str]) -> bool:
    """Heuristic: does a registrable domain plausibly belong to this company?"""
    if not tokens:
        return False
    stem = fold(domain.split(".")[0])
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
            on_cc = bool(prefer_cc) and (
                domain.endswith("." + prefer_cc) or domain.rsplit(".", 1)[-1] == prefer_cc
            )
            if matched and on_cc:
                return f"https://{domain}"  # right name AND right country
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
