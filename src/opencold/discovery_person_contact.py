from __future__ import annotations

from opencold import enricher
from opencold.discovery_data import (
    EMAIL_RE,
    GUESSED_ROLE_EMAILS,
    OUTREACH_USELESS_PREFIXES,
    ROLE_PREFIXES,
)
from opencold.discovery_domains import (
    normalize_domain,
)
from opencold.discovery_models import Contact
from opencold.discovery_person_score import (
    _email_rank,
    _has_contact_page,
    _person_from_text,
)


def find_contact(
    pages: list[enricher.PageContent], domain: str, guess_role_email: bool = False
) -> Contact:
    same_domain_emails = []
    public_person = Contact(contact_type="not_found", confidence=0)
    for page in pages:
        text = "\n".join([page.title, page.description, page.text])
        if not public_person.name:
            name, role = _person_from_text(text)
            if name:
                public_person = Contact(
                    name=name,
                    role=role,
                    contact_type="public_person",
                    confidence=55,
                    source_url=page.url,
                )
        for email in EMAIL_RE.findall(text):
            if normalize_domain(email.split("@", 1)[1]) == domain:
                same_domain_emails.append((email.lower(), page.url))

    seen = set()
    emails = []
    for email, url in same_domain_emails:
        if email not in seen:
            seen.add(email)
            emails.append((email, url))

    if emails:
        ranked = sorted(
            ((email, url, *_email_rank(email, url)) for email, url in emails),
            key=lambda item: item[2],
            reverse=True,
        )
        email, url, rank, name = ranked[0]
        local = email.split("@", 1)[0].lower()
        if local not in ROLE_PREFIXES:
            confidence = min(rank, 95)
            return Contact(
                name=name,
                email=email,
                contact_type="public_email",
                confidence=confidence,
                source_url=url,
            )
        # Skip useless inboxes (support@, contact@, info@, etc.) — treat as no contact
        if local in OUTREACH_USELESS_PREFIXES:
            # Try to find a useful role inbox instead
            for alt_email, alt_url, alt_rank, alt_name in ranked[1:]:
                alt_local = alt_email.split("@", 1)[0].lower()
                if alt_local not in ROLE_PREFIXES:
                    return Contact(
                        name=alt_name,
                        email=alt_email,
                        contact_type="public_email",
                        confidence=min(alt_rank, 95),
                        source_url=alt_url,
                    )
                if alt_local not in OUTREACH_USELESS_PREFIXES:
                    return Contact(
                        email=alt_email,
                        contact_type="role_inbox",
                        confidence=alt_rank,
                        source_url=alt_url,
                    )
            # All emails are useless — fall through to LinkedIn search
        else:
            return Contact(
                email=email,
                contact_type="role_inbox",
                confidence=rank,
                source_url=url,
            )

    contact_page = _has_contact_page(pages)
    if public_person.name:
        return public_person
    if guess_role_email:
        return Contact(
            name=public_person.name,
            role=public_person.role,
            email=f"{GUESSED_ROLE_EMAILS[0]}@{domain}",
            contact_type="role_guess",
            confidence=30,
            source_url=contact_page or public_person.source_url,
        )
    if contact_page:
        return Contact(
            contact_type="contact_page",
            confidence=35,
            source_url=contact_page,
        )

    return Contact(contact_type="not_found", confidence=0)
