from __future__ import annotations

from opencold import enricher
from opencold.discovery_data import (
    B2B_SIGNAL_RE,
    CTA_TEXT,
    NOISY_PRODUCT_RE,
)
from opencold.discovery_domains import (
    _clean_text,
)


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
    facts = " ".join(
        [
            row.get("discovery_reason", ""),
            row.get("company_summary", ""),
            row.get("personalization_facts", ""),
        ]
    )
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
