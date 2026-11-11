"""Candidate company collection across LLM seed, Wikipedia, search and sources channels."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from opencold.discovery_domains import normalize_domain
from opencold.discovery_models import CandidateCompany
from opencold.discovery_query import discover_companies_by_query
from opencold.discovery_region import _region_languages, _resolve_region_key
from opencold.discovery_region_data import _REGION_CCTLD
from opencold.discovery_seed import _resolve_llm_provider, seed_companies_via_llm
from opencold.discovery_sources import _clamp_workers, discover_company_pool
from opencold.discovery_website import resolve_company_website
from opencold.discovery_wiki import wikipedia_company_names


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
