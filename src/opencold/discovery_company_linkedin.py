from __future__ import annotations

import re

from opencold.discovery_contact_data import (
    _LINKEDIN_COMPANY_RE,
)
from opencold.discovery_contact_model import CompanyContacts
from opencold.discovery_search import web_search
from opencold.discovery_website import (
    _company_tokens,
)


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
