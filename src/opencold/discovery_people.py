"""Opt-in person-first discovery: source URLs -> ranked lead rows with a contact."""

from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from opencold import enricher
from opencold.discovery_data import OUTREACH_USELESS_PREFIXES, ROLE_PREFIXES
from opencold.discovery_domains import normalize_domain
from opencold.discovery_icp_score import score_company
from opencold.discovery_lead_score import score_lead
from opencold.discovery_linkedin import search_linkedin_contacts
from opencold.discovery_models import CandidateCompany, Contact
from opencold.discovery_page_search import _merge_pages, search_company_pages
from opencold.discovery_pages import crawl_company_pages
from opencold.discovery_person_contact import find_contact
from opencold.discovery_person_score import score_contact
from opencold.discovery_sources import _clamp_workers, discover_company_pool


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
