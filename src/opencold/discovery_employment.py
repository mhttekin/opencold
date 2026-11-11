from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from opencold.discovery_data import (
    _VERIFY_EMPLOYMENT,
    COMPANY_SUFFIXES_RE,
)
from opencold.discovery_employment_parse import (
    _analyze_engine_results,
)
from opencold.discovery_search_models import SearchResult
from opencold.discovery_search_primary import (
    _ddgs_search,
)


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
