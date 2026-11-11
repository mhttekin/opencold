"""Search-harvest channel: ICP + region query templates -> candidate companies."""

from __future__ import annotations

from itertools import zip_longest
from urllib.parse import urlparse

from opencold import icp_phrases, translator
from opencold.discovery_domains import (
    _company_from_domain,
    _is_blocked_domain,
    _is_blocked_host,
    normalize_domain,
)
from opencold.discovery_models import CandidateCompany
from opencold.discovery_region import MAX_SEARCH_LANGS
from opencold.discovery_search import web_search
from opencold.discovery_search_models import SearchResult
from opencold.discovery_website import _is_directory_domain


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
    # One exact-phrase query per multi-word core chunk ("sustainability
    # consultancy"): search engines treat the quoted form as adjacency, which
    # finds companies the bare bag-of-words queries bury under generic matches.
    templates += [
        f'"{" ".join(chunk)}" {region}' for chunk in icp_phrases.parse_icp(icp).core_phrases
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


def _interleave_translations(texts: list[str], langs: list[str]) -> list[str]:
    """Round-robin interleave native translations (one list per business language)
    with the English originals, native-first, dropping blanks/dupes while preserving
    order. So Morocco [fr, ar] yields fr[0], ar[0], en[0], fr[1], ar[1], en[1], … —
    no single language starves the pool."""
    if not texts:
        return []
    lists: list[list[str]] = []
    for lang in langs:
        nat = [q for q in translator.translate_many(texts, lang, source="en") if q and q.strip()]
        if nat:
            lists.append(nat)
    lists.append(list(texts))  # English last so native languages take priority slots
    seen: set[str] = set()
    out: list[str] = []
    for tup in zip_longest(*lists):
        for q in tup:
            if q and q not in seen:
                seen.add(q)
                out.append(q)
    return out


def discover_companies_by_query(
    icp: str,
    region: str,
    limit: int = 50,
    extra_queries: list[str] | None = None,
    target_langs: list[str] | None = None,
) -> list[CandidateCompany]:
    base = region_query_templates(icp, region)
    extra = list(extra_queries or [])
    langs = list(target_langs or [])[:MAX_SEARCH_LANGS]
    if langs:
        # Native-language queries ("Türkiye'deki kereste firmaları" / "entreprises de
        # recyclage au Maroc") surface real local SMEs that English queries bury under
        # English directory spam. The region name is in every template, so a foreign
        # same-language result (a French firm in a French Morocco search) is region-
        # bounded here and rejected downstream by region_fit.
        queries = _interleave_translations(base, langs)
        queries += _interleave_translations(extra, langs)
    else:
        queries = list(base) + extra
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
