from __future__ import annotations

import re
from urllib.parse import quote_plus

from opencold.discovery_icp_score import _icp_match, _icp_terms
from opencold.discovery_region import (
    _resolve_region_key,
)
from opencold.discovery_website import (
    _company_tokens,
)
from opencold.discovery_wiki_parse import (
    _WIKI_NAME_BLOCKLIST_RE,
    _clean_wiki_name,
    _parse_wikitext_names,
    _wiki_api_get,
)

# ===========================================================================
# Company-first discovery: ICP + region -> ranked company list with a durable
# contact bundle (company email, phone, address, company LinkedIn). Replaces the
# brittle person-finder as the default. Person discovery is available opt-in.
# ===========================================================================


# ---------------------------------------------------------------------------
# Channel A2: Wikipedia "List of <industry> in <region>" name harvest (no LLM)
# ---------------------------------------------------------------------------
#
# Wikipedia curates real, region-scoped company names ("List of insurance
# companies in Bangladesh" -> ~67 insurers) that raw search harvest misses and
# the directory filter actively discards (wikipedia.org is in
# WEBSITE_DIRECTORY_DOMAINS). We mine the page for NAMES only and resolve each to
# its own website via the shared resolver — never treating a wiki URL as a site.
# Purely additive: it augments search harvest and no-ops when no list exists.


def wikipedia_list_titles(icp: str, region: str, limit: int = 3) -> list[str]:
    """Best-matching Wikipedia 'List of ...' page titles for (ICP, region).

    Search returns the *closest* list pages even when none is on-topic (e.g. a
    landscape query surfaces 'List of airlines of the United Kingdom'), so each
    title must independently mention the ICP (morphology-aware) AND the region —
    otherwise we silently no-op rather than harvest a wrong-industry list."""
    icp, region = (icp or "").strip(), (region or "").strip()
    if not icp or not region:
        return []
    icp_terms = _icp_terms(icp)
    region_key = _resolve_region_key(region)

    def _relevant(title: str) -> bool:
        low = title.lower()
        has_icp = bool(_icp_match(icp_terms, title)) if icp_terms else True
        has_region = region.lower() in low or bool(region_key and region_key in low)
        return has_icp and has_region

    titles: list[str] = []
    seen: set[str] = set()
    for q in (f"list of {icp} in {region}", f"list of {icp} of {region}"):
        data = _wiki_api_get(
            {
                "action": "query",
                "list": "search",
                "srsearch": q,
                "srlimit": 5,
                "srnamespace": 0,
            }
        )
        for hit in data.get("query", {}).get("search", []):
            title = hit.get("title", "")
            if title.lower().startswith("list of") and title not in seen and _relevant(title):
                seen.add(title)
                titles.append(title)
        if titles:
            break
    return titles[:limit]


def wikipedia_category_members(icp: str, region: str) -> list[tuple[str, str]]:
    """(name, category_url) members of a likely Wikipedia category (clean supplement)."""
    icp, region = (icp or "").strip(), (region or "").strip()
    if not icp or not region:
        return []
    industry = re.sub(r"\bcompan(y|ies)\b", "", icp, flags=re.IGNORECASE).strip() or icp
    industry = industry[:1].upper() + industry[1:]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for cat in (
        f"Category:{industry} companies of {region}",
        f"Category:{industry} companies in {region}",
    ):
        data = _wiki_api_get(
            {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": cat,
                "cmlimit": 60,
                "cmtype": "page",
                "cmnamespace": 0,
            }
        )
        cat_url = "https://en.wikipedia.org/wiki/" + quote_plus(cat.replace(" ", "_"))
        for m in data.get("query", {}).get("categorymembers", []):
            name = _clean_wiki_name(m.get("title", ""))
            if not (2 <= len(name) <= 80) or _WIKI_NAME_BLOCKLIST_RE.search(name):
                continue
            if not _company_tokens(name) or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append((name, cat_url))
        if out:
            break
    return out


def wikipedia_company_names(icp: str, region: str, max_names: int = 60) -> list[tuple[str, str]]:
    """(name, source_url) candidate companies mined from Wikipedia, no LLM.

    Best-effort and deterministic: returns [] on any failure or when no relevant
    page exists, so the search-harvest channel always carries the request."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _push(name: str, src: str) -> None:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append((name, src))

    for title in wikipedia_list_titles(icp, region):
        data = _wiki_api_get({"action": "parse", "page": title, "prop": "wikitext", "redirects": 1})
        wikitext = (data.get("parse", {}).get("wikitext", {}) or {}).get("*", "")
        src = "https://en.wikipedia.org/wiki/" + quote_plus(title.replace(" ", "_"))
        for name in _parse_wikitext_names(wikitext, max_names=max_names):
            _push(name, src)
        if len(out) >= max_names:
            return out[:max_names]

    for name, cat_url in wikipedia_category_members(icp, region):
        _push(name, cat_url)
        if len(out) >= max_names:
            break
    return out[:max_names]
