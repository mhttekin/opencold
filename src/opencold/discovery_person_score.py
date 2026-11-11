from __future__ import annotations

import re
from urllib.parse import urlparse

from opencold import enricher
from opencold.discovery_data import (
    BAD_PERSON_WORDS,
    EXEC_ROLE_RE,
    HIGH_VALUE_ROLE_PREFIXES,
    LOW_VALUE_ROLE_PREFIXES,
    PERSON_HINT_RE,
    PERSON_LOCAL_RE,
    PERSON_REVERSE_HINT_RE,
    RELEVANT_ROLE_RE,
    ROLE_PREFIXES,
)
from opencold.discovery_domains import (
    _clean_text,
)
from opencold.discovery_models import Contact


def _name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    if local.lower() in ROLE_PREFIXES:
        return ""
    parts = re.split(r"[._+\-]+", local)
    return " ".join(p.capitalize() for p in parts if p and not p.isdigit())


def _valid_person_name(name: str) -> bool:
    value = _clean_text(name.replace("\n", " "))
    if not value or len(value) > 45:
        return False
    parts = value.split()
    if len(parts) < 2:
        return False
    if any(part in BAD_PERSON_WORDS for part in parts):
        return False
    if any(len(part) < 3 for part in parts[1:]):
        return False
    if not all(re.match(r"^[A-Z][a-z]+$", part) for part in parts):
        return False
    return True


def _person_from_text(text: str) -> tuple[str, str]:
    text = _clean_text(text)
    for pattern in (PERSON_HINT_RE, PERSON_REVERSE_HINT_RE):
        match = pattern.search(text or "")
        if not match:
            continue
        name = _clean_text(match.group("name"))
        role = _clean_text(match.group("role")).title()
        if _valid_person_name(name):
            return name, role
    return "", ""


def _has_contact_page(pages: list[enricher.PageContent]) -> str:
    for page in pages:
        if any(part in urlparse(page.url).path.lower() for part in ("contact", "team", "press")):
            return page.url
    return ""


def _email_rank(email: str, source_url: str) -> tuple[int, str]:
    local = email.split("@", 1)[0].lower()
    path = urlparse(source_url).path.lower()
    if local in ROLE_PREFIXES:
        role_rank = {
            "partnerships": 84,
            "partner": 82,
            "growth": 80,
            "marketing": 78,
            "product": 76,
            "sales": 74,
            "team": 62,
            "hello": 58,
            "hi": 55,
            "contact": 54,
            "founders": 46,
            "press": 42,
            "support": 35,
            "info": 30,
        }.get(local, 40)
        return role_rank, ""
    if PERSON_LOCAL_RE.match(local):
        # first@domain is useful, first.last@domain is better.
        rank = 95 if any(sep in local for sep in (".", "_", "-")) else 88
        if any(part in path for part in ("team", "about", "company")):
            rank += 3
        return rank, _name_from_email(email)
    return 50, _name_from_email(email)


def score_contact(contact: Contact) -> tuple[int, str]:
    """Score how useful a discovered contact is for practical outreach."""
    score = 0
    reasons = []
    role = contact.role or ""
    local = contact.email.split("@", 1)[0].lower() if contact.email else ""

    if contact.contact_type == "public_email":
        score += 72
        reasons.append("person_email")
        if contact.name:
            score += 10
            reasons.append("name_from_email")
    elif contact.contact_type == "role_inbox":
        if local in HIGH_VALUE_ROLE_PREFIXES:
            score += 74
            reasons.append("relevant_role_inbox")
        elif local in LOW_VALUE_ROLE_PREFIXES:
            score += 44
            reasons.append("generic_role_inbox")
        else:
            score += 50
            reasons.append("role_inbox")
    elif contact.contact_type == "linkedin_profile":
        if RELEVANT_ROLE_RE.search(role):
            score += 68
            reasons.append("linkedin_relevant_role")
        else:
            score += 55
            reasons.append("linkedin_profile")
    elif contact.contact_type == "public_person":
        if RELEVANT_ROLE_RE.search(role):
            score += 58
            reasons.append("relevant_public_person")
        elif EXEC_ROLE_RE.search(role):
            score += 30
            reasons.append("exec_public_person")
        else:
            score += 40
            reasons.append("public_person")
    elif contact.contact_type == "contact_page":
        score += 28
        reasons.append("contact_page")
    elif contact.contact_type == "role_guess":
        score += 18
        reasons.append("guessed_role_email")

    score += min(contact.confidence // 10, 10)
    if RELEVANT_ROLE_RE.search(role):
        score += 12
        reasons.append("role_relevance")
    if EXEC_ROLE_RE.search(role) and contact.contact_type != "public_email":
        score -= 10
        reasons.append("exec_only")

    return max(0, min(score, 100)), enricher.FACT_SEPARATOR.join(reasons)
