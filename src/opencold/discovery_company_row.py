"""Company row construction and lead scoring for company discovery."""

from __future__ import annotations

import time

from opencold import enricher
from opencold.discovery_company_linkedin import find_company_linkedin
from opencold.discovery_contacts import extract_company_contacts
from opencold.discovery_country import _detected_country
from opencold.discovery_data import B2B_SIGNAL_RE
from opencold.discovery_domains import (
    _company_from_domain,
    _is_aggregator,
    _is_government_domain,
    normalize_domain,
)
from opencold.discovery_icp_score import _icp_evidence, score_company
from opencold.discovery_lead_score import _bad_company_name
from opencold.discovery_linkedin import search_linkedin_contacts
from opencold.discovery_models import CandidateCompany
from opencold.discovery_page_search import _merge_pages, search_company_pages
from opencold.discovery_pages import crawl_company_pages
from opencold.discovery_person_score import _person_from_text
from opencold.discovery_region import _resolve_region_key
from opencold.discovery_region_data import _REGION_CCTLD
from opencold.discovery_region_fit import region_fit
from opencold.discovery_size import size_tier
from opencold.discovery_translation import _localize_enrichment
from opencold.emails import pick_company_email


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
