"""Company discovery orchestrator: candidate pool, row building, judge and ranking."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from opencold import icp_phrases
from opencold.discovery_candidates import discover_company_candidates
from opencold.discovery_classify import _classify_company
from opencold.discovery_company_row import build_company_row
from opencold.discovery_domains import normalize_domain
from opencold.discovery_judge import judge_companies
from opencold.discovery_models import CandidateCompany
from opencold.discovery_region import _region_languages
from opencold.discovery_seed import _resolve_llm_provider
from opencold.discovery_sources import _clamp_workers
from opencold.discovery_translation import _translate_expansion_terms, _translate_profile

# ---------------------------------------------------------------------------
# Orchestrator + CSV writer
# ---------------------------------------------------------------------------


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
