"""LinkedIn profile search for company contacts."""

from __future__ import annotations

import time

from opencold.discovery_data import (
    _LINKEDIN_MAX_QUERIES,
    _LINKEDIN_QUERY_DELAY,
    _VERIFY_EMPLOYMENT,
    LINKEDIN_SEARCH_QUERIES,
    LINKEDIN_TARGET_ROLES_RE,
)
from opencold.discovery_employment import verify_current_employment
from opencold.discovery_employment_parse import _parse_linkedin_title
from opencold.discovery_models import Contact
from opencold.discovery_person_match import _company_name_matches, _is_name_company_coincidence
from opencold.discovery_search import web_search


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
