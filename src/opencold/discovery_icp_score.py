from __future__ import annotations

import re

from opencold import enricher, icp_phrases
from opencold.discovery_models import CandidateCompany
from opencold.icp_phrases import GENERIC_ICP_TERMS
from opencold.icp_phrases import stem as _stem
from opencold.textnorm import fold


def _icp_terms(icp: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9][a-z0-9\-]{2,}", fold(icp)))
    return terms - ({"and", "for", "the", "with", "that", "this"} | GENERIC_ICP_TERMS)


def _icp_match(terms: set[str], text: str) -> list[str]:
    """ICP terms evidenced in `text`. Additive over the old literal-substring test:
    a term matches if its stem equals a whole-word stem in the text (morphology:
    'landscape' ~ 'landscaping') OR a ≥4-char literal term is a substring
    (hyphenated/compound terms like 'tech' in 'fintech' — shorter terms like
    Datamuse's 'urn' would match inside 'journalism'). Returns the original term
    spellings, sorted, so callers can display them as before."""
    if not terms or not text:
        return []
    low = fold(text)
    word_stems = {_stem(tok) for tok in re.findall(r"[a-z0-9]+", low)}
    matched = [t for t in terms if _stem(fold(t)) in word_stems or (len(t) >= 4 and fold(t) in low)]
    return sorted(matched)


def score_company(
    company: CandidateCompany,
    enrichment: dict,
    icp: str,
    extra_terms: set[str] | None = None,
    weak_terms: set[str] | None = None,
    provenance: dict[str, set[str]] | None = None,
) -> tuple[int, str]:
    # NOTE: company.discovery_reason is deliberately excluded — for LLM/search
    # candidates it echoes our own query (e.g. "llm seed: landscape in UK"), so
    # including it made every lead "match" the ICP (a constant 62). Match against
    # the company's own name and crawled content only.
    # extra_terms: native-language ICP terms (e.g. "kereste" for "timber") so a
    # home-language site matches without us translating its text first.
    # weak_terms: semantic-expansion terms (e.g. "sawmill" for "timber") — counted at
    # half weight so a related-only hit never outranks a true ICP / native-term hit.
    # provenance: derived term -> the ICP core token it evidences (see icp_phrases).
    # A derived term that matched is credited ONCE, through its token — otherwise a
    # cluster of same-meaning words (consultancy/consulting/consultant) piles up
    # points for one concept.
    profile = icp_phrases.parse_icp(icp)
    extras = extra_terms or set()
    icp_tokens = set(profile.core_tokens) | set(profile.qualifier_tokens) | _icp_terms(icp)
    weak = (weak_terms or set()) - extras - icp_tokens
    prov_terms = set().union(*provenance.values()) if provenance else set()
    haystack = " ".join(
        [
            company.company,
            enrichment.get("company_summary", ""),
            enrichment.get("personalization_facts", ""),
        ]
    ).lower()

    core = icp_phrases.evidence_core(profile, haystack, provenance)
    matched_extra = _icp_match(extras, haystack)
    matched_weak = _icp_match(weak, haystack)

    base = 35 if enrichment.get("website_status") == "ok" else 15
    # Phrase hit > full core co-occurrence > partial core (half weight). A core
    # token is worth 14 only when the WHOLE core is evidenced; a lone generic
    # head ("consultancy" without "sustainability") scores like a weak term.
    bonus = 18 * len(core.phrase_chunks)
    if core.confirmed:
        bonus += 14 * len(core.required)
    else:
        bonus += 7 * len(core.evidenced)
    bonus += 14 * sum(1 for t in matched_extra if t not in prov_terms)
    bonus += 7 * len(core.matched_qualifiers)
    bonus += 7 * sum(1 for t in matched_weak if t not in prov_terms)
    score = min(100, base + min(bonus, 50))

    display = sorted(
        set(matched_extra) | set(matched_weak) | core.evidenced | set(core.matched_qualifiers)
    )
    parts = [f"phrase:{' '.join(c)}" for c in core.phrase_chunks] + display
    return score, enricher.FACT_SEPARATOR.join(parts)


def _icp_evidence(
    icp: str,
    enrichment: dict,
    extra_terms: set[str] | None = None,
    weak_terms: set[str] | None = None,
    provenance: dict[str, set[str]] | None = None,
) -> bool:
    """True when the ICP's CORE CONCEPT is evidenced in the company's own crawled
    content.

    Content-only (no company name, no discovery_reason): this is the evidence
    used to gate leads, so it must reflect what the site actually says — a company
    literally named 'X Landscapes' should still have to prove it on its pages.

    A multi-word core ("sustainability consultancy") confirms only as a phrase or
    when EVERY required core token is evidenced — each token via its own form, a
    native translation, or an expansion term attributed to it (provenance). A
    partial hit never confirms: matching "consultancy" alone (or its whole
    consulting/advisory cluster) must not verify a sustainability ICP. Qualifier
    tokens ("for SMEs") never confirm on their own.

    extra_terms adds native-language ICP terms, so a home-language site that says
    "kereste" counts as evidence for an English "timber" ICP. weak_terms (semantic
    expansion) mirror their half-weight in scoring: for single-token cores,
    weak-only evidence needs at least two distinct hits. Multi-word cores get NO
    weak fallback at all — expansion tails are unattributed noise (Datamuse gave
    "uganda" and "urn" for "coffee exporter"), and two stray matches on a Ugandan
    news page must never verify a lead whose core concept has zero evidence.
    """
    profile = icp_phrases.parse_icp(icp)
    extras = extra_terms or set()
    icp_tokens = set(profile.core_tokens) | set(profile.qualifier_tokens) | _icp_terms(icp)
    weak = (weak_terms or set()) - extras - icp_tokens
    content = " ".join(
        [
            enrichment.get("company_summary", ""),
            enrichment.get("personalization_facts", ""),
        ]
    )
    core = icp_phrases.evidence_core(profile, content, provenance)
    if core.confirmed:
        return True
    if len(core.required) >= 2:
        return False
    # Single-token or all-generic core: legacy semantics — one native/strong hit
    # confirms, else two weak hits.
    if _icp_match(extras, content):
        return True
    return len(_icp_match(weak, content)) >= 2
