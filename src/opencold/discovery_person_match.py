from __future__ import annotations

import re

from opencold.discovery_data import (
    COMPANY_SUFFIXES_RE,
)
from opencold.textnorm import fold

# ---------------------------------------------------------------------------
# LinkedIn contact discovery via DuckDuckGo search result metadata
# ---------------------------------------------------------------------------


def _company_name_matches(candidate: str, target: str) -> bool:
    """Fuzzy-match a company name from a LinkedIn title against the target."""

    def _normalize(name: str) -> str:
        return fold(COMPANY_SUFFIXES_RE.sub("", name).strip())

    c = _normalize(candidate)
    t = _normalize(target)
    if not c or not t:
        return False
    if c == t:
        return True
    # For short single-word company names, require exact word boundary match
    # to avoid "Framer" matching "Framerfry" or "FramerExperts"
    if " " not in t and len(t) <= 10:
        # Target is a short single word — only match if it appears as a
        # standalone word in the candidate, or candidate is contained in target
        if c in t:
            return True
        if re.search(r"\b" + re.escape(t) + r"\b", c):
            return True
        return False
    if c in t or t in c:
        return True
    c_tokens = set(c.split())
    t_tokens = set(t.split())
    if not c_tokens or not t_tokens:
        return False
    overlap = len(c_tokens & t_tokens) / max(len(c_tokens), len(t_tokens))
    return overlap > 0.5


def _is_name_company_coincidence(name: str, company: str, linkedin_url: str) -> bool:
    """Detect when a person's name coincidentally matches the company name.

    Example: "Matt Crisp" found for company "Crisp" — the URL /in/mattcrisp
    is just the person's name, and "Crisp" in the LinkedIn title is their
    surname, not their employer.
    """
    name_parts = name.lower().split()
    if len(name_parts) < 2:
        return False
    company_lower = company.lower().strip()
    first_name = name_parts[0]
    last_name = name_parts[-1]
    # Check if person's first or last name matches the company name
    name_matches_company = (
        last_name == company_lower or company_lower in last_name or first_name == company_lower
    )
    if not name_matches_company:
        return False

    # If the person's last name IS the company name (single-word company),
    # this is very likely a coincidence — verify via URL slug
    slug = linkedin_url.rstrip("/").rsplit("/", 1)[-1].lower()
    # Remove LinkedIn dedup suffixes (e.g., -258a1651, -3a69205, -12345)
    slug_clean = re.sub(r"[-_][0-9a-f]{4,}$", "", slug)
    slug_clean = re.sub(r"[-_]?\d+$", "", slug_clean)

    # Build expected slug patterns from the name
    first = name_parts[0]
    name_slugs = {
        f"{first}{last_name}",  # mattcrisp
        f"{first}-{last_name}",  # matt-crisp
        f"{first}_{last_name}",  # matt_crisp
        f"{last_name}{first}",  # crispmatt
        f"{last_name}-{first}",  # crisp-matt
        f"{first}{last_name[0]}",  # mattc
        f"{first[0]}{last_name}",  # mcrisp
    }
    # For multi-part names (e.g., "Mixo Oral Baloyi"), also try middle+last combos
    if len(name_parts) > 2:
        middle_parts = name_parts[1:-1]
        for mid in middle_parts:
            name_slugs.add(f"{first}-{mid}-{last_name}")
            name_slugs.add(f"{first}{mid}{last_name}")
    if slug_clean in name_slugs:
        return True

    # For single-word short company names that match the person's first or last name,
    # the coincidence rate is very high (e.g., "Crisp" company matching anyone named Crisp,
    # or "Mixo" company matching someone whose first name is Mixo).
    matching_name = None
    if " " not in company_lower:
        if last_name == company_lower:
            matching_name = last_name
        elif first_name == company_lower:
            matching_name = first_name
    if matching_name:
        # If slug doesn't contain the company name as part of a non-name pattern,
        # it's likely a name coincidence
        if company_lower not in slug_clean:
            return True
        # If slug IS a name pattern even after not matching our exact patterns above,
        # check if it's very short or random (like 'label23') — still a coincidence
        if len(slug_clean) < 10 and not any(c in slug_clean for c in company_lower):
            return True

    return False
