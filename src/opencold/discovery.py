"""Source-grounded company and contact discovery."""

from __future__ import annotations

import csv
import json
import os  # noqa: F401
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field  # noqa: F401
from itertools import zip_longest
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse  # noqa: F401

from bs4 import BeautifulSoup  # noqa: F401

from opencold import discovery_reacher, enricher, icp_phrases, translator
from opencold import regions_data as rd  # noqa: F401
from opencold.discovery_classify import _classify_company
from opencold.discovery_company_csv import write_company_csv  # noqa: F401
from opencold.discovery_contact_data import (
    _LINKEDIN_COMPANY_RE,
    _PHONE_RE,  # noqa: F401
    _SOCIAL_HOSTS,  # noqa: F401
    PARTNERSHIP_PATH_HINTS,  # noqa: F401
)
from opencold.discovery_contact_data import (
    COMPANY_EMAIL_PRIORITY as COMPANY_EMAIL_PRIORITY,
)
from opencold.discovery_contact_model import _CONTACT_PATHS, CompanyContacts  # noqa: F401
from opencold.discovery_contacts import (
    _extract_jsonld_org,  # noqa: F401
    _register_social,  # noqa: F401
    extract_company_contacts,
)
from opencold.discovery_country import _detect_phone_country, _detected_country  # noqa: F401
from opencold.discovery_csv import COMPANY_CSV_FIELDS, COMPANY_PEOPLE_FIELDS, WALL_BANNER  # noqa: F401
from opencold.discovery_data import (
    _COMPANY_NAME_PAT as _COMPANY_NAME_PAT,
)
from opencold.discovery_data import (
    _EMPLOYMENT_DATE_RE,  # noqa: F401
    _LINKEDIN_MAX_QUERIES,
    _LINKEDIN_QUERY_DELAY,
    _MOVED_PATTERNS,  # noqa: F401
    _NOT_EMPLOYED_RE,  # noqa: F401
    _SEARXNG_INSTANCES,  # noqa: F401
    _VERIFY_EMPLOYMENT,
    B2B_SIGNAL_RE,
    BAD_PERSON_WORDS,  # noqa: F401
    COMPANY_SUFFIXES_RE,
    CTA_TEXT,  # noqa: F401
    DISCOVERY_PATHS,  # noqa: F401
    EMAIL_RE,  # noqa: F401
    EXEC_ROLE_RE,  # noqa: F401
    GUESSED_ROLE_EMAILS,  # noqa: F401
    HIGH_VALUE_ROLE_PREFIXES,  # noqa: F401
    INTERNAL_DETAIL_HINTS,  # noqa: F401
    INTERNAL_SKIP_PARTS,  # noqa: F401
    LINKEDIN_SEARCH_QUERIES,
    LINKEDIN_TARGET_ROLES_RE,
    LINKEDIN_TITLE_RE,  # noqa: F401
    LOW_VALUE_ROLE_PREFIXES,  # noqa: F401
    NOISY_PRODUCT_RE,  # noqa: F401
    OUTREACH_USELESS_PREFIXES,
    PERSON_HINT_RE,  # noqa: F401
    PERSON_LOCAL_RE,  # noqa: F401
    PERSON_REVERSE_HINT_RE,  # noqa: F401
    RELEVANT_ROLE_RE,  # noqa: F401
    ROLE_PREFIXES,
    SEARCH_FETCH_MULTIPLIER,
    SEARCH_PAGE_LIMIT,
    SEARCH_PATH_HINTS,
    SEARCH_QUERIES,
    SEARCH_RESULT_LIMIT,
    SEARCH_TIMEOUT,
)
from opencold.discovery_data import BLOCKED_DOMAINS as BLOCKED_DOMAINS
from opencold.discovery_data import BLOCKED_HOST_PARTS as BLOCKED_HOST_PARTS
from opencold.discovery_data import SPACE_RE as SPACE_RE
from opencold.discovery_domains import (
    _AGGREGATOR_DOMAINS as _AGGREGATOR_DOMAINS,
)
from opencold.discovery_domains import (
    _AGGREGATOR_RE as _AGGREGATOR_RE,
)
from opencold.discovery_domains import (
    _AGGREGATOR_STEMS as _AGGREGATOR_STEMS,
)
from opencold.discovery_domains import (
    _SECOND_LEVEL_TLDS as _SECOND_LEVEL_TLDS,
)
from opencold.discovery_domains import (
    _clean_text as _clean_text,
)
from opencold.discovery_domains import (
    _company_from_anchor as _company_from_anchor,
)
from opencold.discovery_domains import (
    _company_from_domain as _company_from_domain,
)
from opencold.discovery_domains import (
    _is_aggregator as _is_aggregator,
)
from opencold.discovery_domains import (
    _is_blocked_domain as _is_blocked_domain,
)
from opencold.discovery_domains import (
    _is_blocked_host as _is_blocked_host,
)
from opencold.discovery_domains import (
    _is_government_domain as _is_government_domain,
)
from opencold.discovery_domains import (
    _registrable_domain as _registrable_domain,
)
from opencold.discovery_domains import (
    normalize_domain as normalize_domain,
)
from opencold.discovery_employment_parse import (
    _COMMON_ROLES_RE,  # noqa: F401
    _analyze_engine_results,
    _check_employment_dates,  # noqa: F401
    _company_in_title,  # noqa: F401
    _extract_linkedin_company_from_title,  # noqa: F401
    _parse_linkedin_title,
)
from opencold.discovery_icp_score import _icp_evidence, _icp_match, _icp_terms, score_company
from opencold.discovery_judge import (
    _JUDGE_SYSTEM,  # noqa: F401
    _build_judge_prompt,  # noqa: F401
    _country_matches,  # noqa: F401
    judge_companies,
)
from opencold.discovery_lead_score import _bad_company_name, score_lead
from opencold.discovery_linkedin_parse import parse_linkedin_result_titles  # noqa: F401
from opencold.discovery_models import CandidateCompany, Contact
from opencold.discovery_pages import crawl_company_pages
from opencold.discovery_person_contact import find_contact
from opencold.discovery_person_match import _company_name_matches, _is_name_company_coincidence
from opencold.discovery_person_score import (
    _email_rank,  # noqa: F401
    _has_contact_page,  # noqa: F401
    _name_from_email,  # noqa: F401
    _person_from_text,
    _valid_person_name,  # noqa: F401
    score_contact,
)
from opencold.discovery_region import (
    _HQ_ADJ_RE,  # noqa: F401
    _HQ_CUSTOMER_RE,  # noqa: F401
    _HQ_PLACE,  # noqa: F401
    _HQ_VERB_RE,  # noqa: F401
    MAX_SEARCH_LANGS,
    _detect_address_country,  # noqa: F401
    _detect_domain_country,  # noqa: F401
    _detect_prose_location,  # noqa: F401
    _region_language,  # noqa: F401
    _region_languages,
    _resolve_place,  # noqa: F401
    _resolve_region_key,
    _target_region_tokens,  # noqa: F401
)
from opencold.discovery_region_data import (
    _AMBIGUOUS as _AMBIGUOUS,
)
from opencold.discovery_region_data import (
    _COUNTRY_DEMONYMS as _COUNTRY_DEMONYMS,
)
from opencold.discovery_region_data import (
    _COUNTRY_DEMONYMS_BY_LEN as _COUNTRY_DEMONYMS_BY_LEN,
)
from opencold.discovery_region_data import (
    _COUNTRY_NAMES as _COUNTRY_NAMES,
)
from opencold.discovery_region_data import (
    _COUNTRY_NAMES_BY_LEN as _COUNTRY_NAMES_BY_LEN,
)
from opencold.discovery_region_data import (
    _PHONE_CC as _PHONE_CC,
)
from opencold.discovery_region_data import (
    _REGION_ALIASES as _REGION_ALIASES,
)
from opencold.discovery_region_data import (
    _REGION_CCTLD as _REGION_CCTLD,
)
from opencold.discovery_region_data import (
    _REGION_CITIES as _REGION_CITIES,
)
from opencold.discovery_region_data import (
    _REGION_LANGS as _REGION_LANGS,
)
from opencold.discovery_region_data import (
    _REGION_PHONE as _REGION_PHONE,
)
from opencold.discovery_region_data import (
    _build_phone_cc as _build_phone_cc,
)
from opencold.discovery_region_fit import region_fit
from opencold.discovery_search import web_search
from opencold.discovery_search_fallback import _ddg_html_search, _mojeek_search, _searxng_search  # noqa: F401
from opencold.discovery_search_html import _duckduckgo_search_urls, _fetch_search_html  # noqa: F401
from opencold.discovery_search_models import SearchResult
from opencold.discovery_search_parse import _unwrap_duckduckgo_url, parse_search_result_urls  # noqa: F401
from opencold.discovery_search_primary import (
    _brave_search,  # noqa: F401
    _ddgs_search,
    _get_serper_key,  # noqa: F401
    _serper_search,  # noqa: F401
)
from opencold.discovery_seed import (
    _SEED_SYSTEM,  # noqa: F401
    _build_seed_prompt,  # noqa: F401
    _parse_json_object,  # noqa: F401
    _resolve_llm_provider,
    seed_companies_via_llm,
)
from opencold.discovery_size import size_tier
from opencold.discovery_size_data import _SIZE_BAND_RE, _SME_HINT_RE  # noqa: F401
from opencold.discovery_sources import (
    _PROJECT_ROOT,  # noqa: F401
    _clamp_workers,
    _fetch_source,  # noqa: F401
    _internal_detail_links,  # noqa: F401
    discover_companies,  # noqa: F401
    discover_company_pool,
    discover_from_source,  # noqa: F401
    extract_companies_from_html,  # noqa: F401
    load_sources,  # noqa: F401
)
from opencold.discovery_translation import (
    _NATIVE_FUNCTION_WORDS,  # noqa: F401
    _localize_enrichment,
    _translate_expansion_terms,
    _translate_icp_terms,  # noqa: F401
    _translate_one,  # noqa: F401
    _translate_profile,
    _translate_terms,  # noqa: F401
    _translated_term_ok,  # noqa: F401
)
from opencold.emails import pick_company_email

# Re-exported names: tests and icp_expansion resolve these via opencold.discovery.
from opencold.icp_phrases import GENERIC_ICP_TERMS  # noqa: F401
from opencold.icp_phrases import stem as _stem  # noqa: F401
from opencold.phones import calling_code, region_hint  # noqa: F401
from opencold.phones import normalize_phone as _clean_phone  # noqa: F401
from opencold.textnorm import fold

# Re-export the Reacher helpers and constants from their owner.
_REACHER_VERSION = discovery_reacher._REACHER_VERSION
_REACHER_BIN_DIR = discovery_reacher._REACHER_BIN_DIR
_REACHER_BIN_NAME = discovery_reacher._REACHER_BIN_NAME
_reacher_target_triple = discovery_reacher._reacher_target_triple
_download_reacher = discovery_reacher._download_reacher
_find_reacher_binary = discovery_reacher._find_reacher_binary
_reacher_check = discovery_reacher._reacher_check
_generate_email_patterns = discovery_reacher._generate_email_patterns
_guess_email_from_name = discovery_reacher._guess_email_from_name


def __getattr__(name: str) -> str | None | bool:
    # The owner rebinds the cache as it resolves the binary. Expose its current value.
    if name == "_REACHER_BIN":
        return discovery_reacher._REACHER_BIN
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
        futures = {executor.submit(fn, q, 5): label for label, (q, fn) in queries.items()}
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

    # Aggregate signals
    any_confirms = any(a["confirms"] for a in engine_analyses.values())
    any_contradicts = any(a["contradicts"] for a in engine_analyses.values())
    any_not_employed = any(a["not_employed"] for a in engine_analyses.values())
    moved_to_companies = [a["moved_to"] for a in engine_analyses.values() if a["moved_to"]]
    other_companies = [a["other_company"] for a in engine_analyses.values() if a["other_company"]]
    confirming_sources = [e for e, a in engine_analyses.items() if a["confirms"]]

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
        other = site_analysis["other_company"] or (
            other_companies[0] if other_companies else "unknown"
        )
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
            contacts.append(
                Contact(
                    name=name,
                    role=role.strip().rstrip(",").strip(),
                    contact_type="linkedin_profile",
                    confidence=confidence,
                    source_url=result.url,
                )
            )
            found_any = True
        if found_any:
            break  # short-circuit: first successful query is enough

    # Sort by role relevance: targeted roles first
    contacts.sort(key=lambda c: 0 if LINKEDIN_TARGET_ROLES_RE.search(c.role or "") else 1)

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
                verified.append(
                    Contact(
                        name=contact.name,
                        role=contact.role,
                        contact_type=contact.contact_type,
                        confidence=confidence,
                        source_url=contact.source_url,
                    )
                )
            elif "contradict" in reason or "moved_to" in reason or "not_currently" in reason:
                any_hard_reject = True
            time.sleep(0.3)
        if verified:
            return verified
        # Only use fallback for soft rejections (no results, search failed, etc.)
        # If verification explicitly contradicted, don't return the contact
        if not any_hard_reject and contacts[0].confidence >= 70:
            return [
                Contact(
                    name=contacts[0].name,
                    role=contacts[0].role,
                    contact_type=contacts[0].contact_type,
                    confidence=max(contacts[0].confidence - 20, 30),
                    source_url=contacts[0].source_url,
                )
            ]
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
    companies = discover_company_pool(
        sources, limit=limit, source_limit=source_limit, workers=workers
    )
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
        contact = find_contact(
            pages, normalize_domain(company.website), guess_role_email=guess_role_email
        )
        # Check if this is a useless role inbox (support@, contact@, info@, etc.)
        _is_useless_inbox = (
            contact.contact_type == "role_inbox"
            and contact.email
            and contact.email.split("@", 1)[0].lower() in OUTREACH_USELESS_PREFIXES
        )
        # LinkedIn fallback for weak or useless contacts
        if (
            contact.contact_type in ("public_person", "contact_page", "role_guess", "not_found")
            or _is_useless_inbox
        ):
            linkedin_contacts = search_linkedin_contacts(
                company.company, normalize_domain(company.website)
            )
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
        if (
            contact.contact_type == "role_inbox"
            and contact.email
            and contact.email.split("@", 1)[0].lower() in OUTREACH_USELESS_PREFIXES
        ):
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
        "email",
        "first_name",
        "last_name",
        "company",
        "website",
        "discovery_source_url",
        "discovery_reason",
        "lead_score",
        "lead_score_reasons",
        "icp_score",
        "matched_terms",
        "contact_name",
        "contact_role",
        "contact_email",
        "contact_type",
        "contact_confidence",
        "contact_score",
        "contact_score_reasons",
        "contact_source_url",
        "website_status",
        "company_summary",
        "personalization_facts",
        "source_urls",
        "personalization_score",
        "quality_warnings",
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

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_WIKI_UA = "opencold/0.1 (company discovery channel)"

# Section headings whose entries are not active target companies.
_WIKI_SKIP_SECTIONS = (
    "defunct",
    "former",
    "closed",
    "merged",
    "dissolved",
    "renamed",
    "regulator",
    "regulators",
    "association",
    "associations",
    "see also",
    "references",
    "external links",
    "further reading",
    "notes",
    "bibliography",
)

# Names that are clearly not operating companies (regulators/indexes/meta).
_WIKI_NAME_BLOCKLIST_RE = re.compile(
    r"\b(authority|regulator|ministry|commission|federation|institute|academy|"
    r"index|list of|category|wikipedia|template|portal|see also)\b",
    re.IGNORECASE,
)


def _wiki_api_get(params: dict) -> dict:
    """GET the MediaWiki API as JSON. Returns {} on failure (best-effort).

    Retries once: Wikipedia occasionally times out / rate-limits, and a silent
    empty would drop the whole channel for the request (search harvest still
    covers it, but a cheap retry recovers most transient misses)."""
    url = WIKIPEDIA_API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": _WIKI_UA})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT + 5) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
    return {}


def _clean_wiki_name(raw: str) -> str:
    """Reduce a wikitext fragment to a bare company name.

    Resolves [[target|text]] to text, strips refs/comments/templates/HTML and
    bold/italic markup, then cuts at a description separator (spaced dash or an
    opening paren) so 'Acme Ltd – the best (est. 1990)' -> 'Acme Ltd'. Keeps
    intra-name hyphens like 'Bradley-Hole' (only spaced dashes split)."""
    s = raw or ""
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]", r"\1", s)  # [[a|b]] -> b
    s = re.sub(r"<ref[^>]*?/>", "", s)
    s = re.sub(r"<ref.*?</ref>", "", s, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)
    s = re.sub(r"\{\{.*?\}\}", "", s, flags=re.DOTALL)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.split(r"\s+[-–—]\s+|\s*\(", s, maxsplit=1)[0]  # cut description
    s = re.sub(r"[\[\]{}|*#]", "", s)
    return _clean_text(s).strip(" .,-–—\t")


def _wikitable_first_cells(block: str) -> list[str]:
    """First data cell of each row in a {| ... |} wikitable block."""
    cells: list[str] = []
    for row in re.split(r"\n\s*\|-+", block):
        for line in row.splitlines():
            s = line.strip()
            if not s or s.startswith(("{|", "|}", "|+")):
                continue
            if s.startswith("!"):  # header row — no data cell
                break
            if s.startswith("|"):
                cell = s[1:]
                if "||" in cell:  # inline row: keep the first cell
                    cell = cell.split("||", 1)[0]
                if "|" in cell:  # strip a "style=...|" cell attribute
                    left, right = cell.split("|", 1)
                    if "=" in left and len(left) < 60:
                        cell = right
                cells.append(cell)
                break
    return cells


def _parse_wikitext_names(wikitext: str, max_names: int = 80) -> list[str]:
    """Candidate company names from a 'List of ...' page's wikitext.

    Handles the layouts these pages actually use: [[wikilinks]], bullet lists
    (incl. {{columns-list}}/{{div col}}), and the first column of {| wikitables.
    Section-aware: entries under Defunct/Regulators/See also/References/etc. are
    skipped. Heuristic by design — downstream ICP+region verification drops junk."""
    if not wikitext:
        return []
    names: list[str] = []
    seen: set[str] = set()

    def _emit(raw: str) -> None:
        name = _clean_wiki_name(raw)
        if not (2 <= len(name) <= 80) or _WIKI_NAME_BLOCKLIST_RE.search(name):
            return
        if not _company_tokens(name):
            return
        key = name.lower()
        if key not in seen:
            seen.add(key)
            names.append(name)

    skip = False
    in_table = False
    table_lines: list[str] = []
    for line in wikitext.splitlines():
        s = line.strip()
        heading = re.match(r"^=+\s*(.+?)\s*=+\s*$", s)
        if heading:
            skip = any(sec in heading.group(1).lower() for sec in _WIKI_SKIP_SECTIONS)
            continue
        if skip:
            continue
        if s.startswith("{|"):
            in_table, table_lines = True, [line]
            continue
        if in_table:
            table_lines.append(line)
            if s.startswith("|}"):
                for cell in _wikitable_first_cells("\n".join(table_lines)):
                    _emit(cell)
                in_table, table_lines = False, []
            continue
        bullet = re.match(r"^\*+\s*(.+)$", s)
        if bullet:
            _emit(bullet.group(1))
        elif s.startswith("[[") and "]]" in s:
            _emit(s)
        if len(names) >= max_names:
            break
    return names[:max_names]


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


def _resolve_names(names: list[str], icp: str, region: str, workers: int) -> list[tuple[str, str]]:
    """Resolve company names to (name, website) via search, in parallel.

    Shared by the LLM seed and Wikipedia channels: disambiguates namesakes with
    ICP+region context and prefers the target country's ccTLD."""
    if not names:
        return []
    context = f"{icp} {region}".strip()
    prefer_cc = _REGION_CCTLD.get(_resolve_region_key(region) or "")
    worker_n = max(1, min(_clamp_workers(workers), len(names)))
    resolved: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=worker_n) as executor:
        future_to_name = {
            executor.submit(
                resolve_company_website, n, require_match=True, context=context, prefer_cc=prefer_cc
            ): n
            for n in names
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            try:
                url = future.result()
            except Exception:
                url = None
            if url:
                resolved.append((name, url))
    return resolved


def discover_company_candidates(
    icp: str,
    region: str,
    sources: list[str] | None = None,
    limit: int = 50,
    workers: int = 8,
    use_llm: bool = True,
    seed_count: int = 30,
    use_wiki: bool = True,
    use_translation: bool = True,
    expansion: set[str] | None = None,
    use_expansion: bool = True,
) -> list[CandidateCompany]:
    """Collect candidate companies from LLM seeding (A), Wikipedia lists (A2),
    search harvest (B), and an optional manual sources file (C). Deduped by
    registrable domain; first channel to surface a domain wins and tags it.

    A2 and B are additive and always run (subject to use_wiki); they collaborate
    so every request is served by search harvest at minimum, with LLM/Wikipedia
    layering curated names on top."""
    candidates: dict[str, CandidateCompany] = {}
    target_langs = _region_languages(region) if use_translation else []

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
            seed = seed_companies_via_llm(
                icp, region, count=seed_count, provider_config=prov, related=expansion
            )
            extra_queries = [f"{d} {region}" for d in seed.get("local_directories", [])]
            for name, url in _resolve_names(seed.get("companies", []), icp, region, workers):
                _add(
                    CandidateCompany(
                        company=name,
                        website=url,
                        discovery_source_url=url,
                        discovery_reason=f"llm seed: {icp} in {region}",
                    ),
                    "llm",
                )

    # Bounded expansion queries (top-N related terms, ONE template each) appended to
    # the search-harvest extras — capped in expansion_queries to avoid a query explosion.
    if use_expansion and expansion:
        from opencold import icp_expansion

        extra_queries += icp_expansion.expansion_queries(expansion, region)

    # Channel A2: Wikipedia "List of ..." names (deterministic, no LLM). Additive.
    if use_wiki:
        wiki = wikipedia_company_names(icp, region, max_names=seed_count)
        wiki_src = {name: src for name, src in wiki}
        for name, url in _resolve_names([name for name, _ in wiki], icp, region, workers):
            _add(
                CandidateCompany(
                    company=name,
                    website=url,
                    discovery_source_url=wiki_src.get(name, url),
                    discovery_reason=f"wikipedia list: {icp} in {region}",
                ),
                "wikipedia",
            )

    # Channel B: search harvest (always runs).
    for cand in discover_companies_by_query(
        icp, region, limit=limit, extra_queries=extra_queries, target_langs=target_langs
    ):
        _add(cand, "search")

    # Channel C: optional manual sources (back-compat power-user channel).
    if sources:
        for cand in discover_company_pool(sources, limit=limit, workers=workers):
            _add(cand, "sources")

    return list(candidates.values())[: max(limit, 1)]


def _linkedin_slug_matches(url: str, company: str, domain: str) -> bool:
    """Does a linkedin.com/company/<slug> plausibly belong to this company?

    Search results for small companies are noisy — without this check the first
    hit wins, attaching unrelated profiles (e.g. /company/cotiviti to "Macarpa").
    Compares the slug against the company-name tokens and the domain stem; tiny
    slugs (e.g. /company/t) can match anything, so they never pass.
    """
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    slug_compact = re.sub(r"[^a-z0-9]", "", slug)
    if len(slug_compact) < 3:
        return False
    stem = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
    candidates = {stem, "".join(_company_tokens(company))}
    candidates |= {t for t in _company_tokens(company) if len(t) >= 4}
    return any(c and (c in slug_compact or slug_compact in c) for c in candidates if len(c) >= 3)


def find_company_linkedin(company: str, contacts: CompanyContacts, domain: str) -> str:
    if contacts.linkedin_company_url:
        return contacts.linkedin_company_url
    try:
        for result in web_search(f'"{company}" site:linkedin.com/company', num=5):
            match = _LINKEDIN_COMPANY_RE.search(result.url)
            if not match:
                continue
            url = match.group(0).split("?")[0]
            if _linkedin_slug_matches(url, company, domain):
                return url
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Orchestrator + CSV writer
# ---------------------------------------------------------------------------


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
    if B2B_SIGNAL_RE.search(
        " ".join([row.get("company_summary", ""), row.get("personalization_facts", "")])
    ):
        score += 6
        reasons.append("b2b_signal")
    return max(0, min(score, 100)), enricher.FACT_SEPARATOR.join(reasons)


def build_company_row(
    company: CandidateCompany,
    icp: str,
    region: str,
    max_pages: int = 4,
    find_people: bool = False,
    target_langs: list[str] | None = None,
    extra_terms: set[str] | None = None,
    weak_terms: set[str] | None = None,
    provenance: dict[str, set[str]] | None = None,
) -> dict | None:
    domain = normalize_domain(company.website)
    # Union of native (full-weight) + expansion (half-weight) terms for the boolean
    # evidence/localize checks, where weighting does not matter.
    all_extra = (extra_terms or set()) | (weak_terms or set())
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
    # Translate a home-language site's facts into English when the English/native
    # ICP terms find no evidence, so matching, the judge, and the CSV read English.
    if target_langs:
        enrichment = _localize_enrichment(enrichment, icp, all_extra, provenance)
    pages_text = " ".join(f"{p.title} {p.description} {p.text}" for p in pages)

    cc = _REGION_CCTLD.get(_resolve_region_key(region) or "", "")
    contacts = extract_company_contacts(company.website, max_pages, cc)
    name = company.company
    if (
        contacts.company_name
        and not _bad_company_name(contacts.company_name)
        and (not name or name == _company_from_domain(domain) or _bad_company_name(name))
    ):
        name = contacts.company_name
    if _bad_company_name(name):
        # Anchor/title scrape produced junk (SEO keyword stuffing, 100-char titles)
        # and the site offered nothing structured — the domain stem beats garbage.
        name = _company_from_domain(domain)

    page_person = _person_from_text(pages_text)[0]  # a named person on the site, if any
    email, email_type, _email_src = pick_company_email(contacts.emails, domain, [page_person])
    linkedin = find_company_linkedin(name, contacts, domain)
    rfit, rfit_reasons = region_fit(contacts, company.website, region, pages_text)
    region_conflict = "region_conflict" in rfit_reasons
    region_anchor = any(
        a in rfit_reasons for a in ("cctld:", "phone:", "addr_region_match", "hq_region_match")
    )
    detected = _detected_country(contacts, company.website, enrichment.get("company_summary", ""))
    tier = size_tier(pages_text, contacts)

    if contacts.partnership_url:
        partnership = f"page:{contacts.partnership_url}"
    elif email and email.split("@", 1)[0].lower() in ("partnerships", "partner", "bd"):
        partnership = f"email:{email}"
    else:
        partnership = ""

    icp_score, matched_terms = score_company(
        company, enrichment, icp, extra_terms, weak_terms, provenance
    )
    if rfit_reasons:
        matched_terms = (
            matched_terms + (enricher.FACT_SEPARATOR if matched_terms else "") + rfit_reasons
        )

    row = {
        "email": email,
        "name": "",
        "company": name,
        "website": company.website,
        "country": detected.title() if detected else region,
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
        row,
        rfit,
        email_type,
        region_targeted=bool(region),
        region_conflict=region_conflict,
    )
    row["lead_score"] = str(lead_score)
    row["lead_score_reasons"] = lead_reasons
    # Carried for verification/classification; underscore keys are not written to
    # CSV (DictWriter uses fixed fieldnames + extrasaction="ignore").
    row["_icp_evidence"] = _icp_evidence(icp, enrichment, extra_terms, weak_terms, provenance)
    row["_region_conflict"] = region_conflict
    row["_region_anchor"] = region_anchor
    row["_is_aggregator"] = _is_aggregator(
        domain,
        " ".join(
            [
                enrichment.get("company_summary", ""),
                enrichment.get("personalization_facts", ""),
            ]
        ),
    )
    row["_is_government"] = _is_government_domain(domain)

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
    use_wiki: bool = True,
    use_translation: bool = True,
    use_expansion: bool = True,
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
    # Resolve the target language(s) once, and translate the ICP profile once per
    # language, so the native-language matcher terms are reused across every company
    # (not per row). Multilingual markets (morocco -> fr+ar) get every language.
    # `provenance` maps each ICP token to the derived terms (native translations,
    # expansion-cluster members) that evidence it — the phrase-aware gate needs the
    # attribution, not just the flat sets.
    profile = icp_phrases.parse_icp(icp)
    target_langs = _region_languages(region) if use_translation else []
    extra_terms: set[str] = set()
    weak_terms: set[str] = set()
    provenance: dict[str, set[str]] = {}

    def _attribute(token: str, terms: set[str]) -> None:
        if terms:
            provenance.setdefault(token, set()).update(terms)

    for lang in target_langs:
        strong_nat, weak_nat, prov_nat = _translate_profile(profile, lang)
        extra_terms |= strong_nat
        weak_terms |= weak_nat
        for token, terms in prov_nat.items():
            _attribute(token, terms)
    # Semantic ICP expansion (e.g. "timber" -> sawmill/plywood), computed once and
    # reused across every company: English terms widen matching directly; their native
    # translations widen home-language matching; a bounded few also drive extra search
    # queries (inside discover_company_candidates).
    expansion: set[str] = set()
    if use_expansion:
        from opencold import icp_expansion

        grouped = icp_expansion.expand_icp_grouped(
            icp,
            use_llm=use_llm,
            provider=_resolve_llm_provider() if use_llm else None,
        )
        expansion = grouped.flat
        weak_terms |= grouped.flat
        for token, terms in grouped.by_token.items():
            _attribute(token, terms)
        # Translate ONLY curated terms to native (plywood -> kontrplak), per language,
        # token by token so the native forms stay attributed. Datamuse-tail
        # translations spawn generic native words (e.g. "alan") that match.
        curated_grouped = icp_expansion.curated_terms_grouped(icp)
        for lang in target_langs:
            for token, terms in curated_grouped.items():
                native, safe = _translate_expansion_terms(terms & expansion, lang)
                weak_terms |= native
                _attribute(token, safe)
    candidates = discover_company_candidates(
        icp,
        region,
        sources=sources,
        limit=pool,
        workers=workers,
        use_llm=use_llm,
        seed_count=seed_count,
        use_wiki=use_wiki,
        use_translation=use_translation,
        expansion=expansion,
        use_expansion=use_expansion,
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
            executor.submit(
                build_company_row,
                company,
                icp,
                region,
                max_pages,
                find_people,
                target_langs,
                extra_terms,
                weak_terms,
                provenance,
            ): company
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
            row,
            bool(row.get("_icp_evidence")),
            bool(row.get("_region_conflict")),
            verdicts.get(idx),
        )
        row["match_confidence"] = confidence
        row["verification"] = why

    def _rank(row: dict) -> int:
        return int(row.get("lead_score", "0"))

    verified = sorted(
        (r for r in rows if r["match_confidence"] == "verified"), key=_rank, reverse=True
    )
    review = sorted((r for r in rows if r["match_confidence"] == "review"), key=_rank, reverse=True)
    rejected = sorted(
        (r for r in rows if r["match_confidence"] == "rejected"), key=_rank, reverse=True
    )

    # Verified fill the Top-N; the review/rejected pile (capped) goes below the wall.
    return verified[:limit] + (review + rejected)[:limit]
