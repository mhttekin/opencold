"""Company email selection: drop placeholders, then classify person vs role inbox.

A mailbox is a `person_email` only when its local-part matches a person name we
actually know (from the page, the Companies House officer list, or contact fields).
Everything else is a `role_inbox` -- we never guess personhood from the shape of
the local-part ("palet@", "service-cooling@" are not people).
"""

from __future__ import annotations

import re

from opencold.textnorm import fold

# RFC 2606 / 6761 reserved names: never a real mailbox.
RESERVED_TLDS = {"test", "invalid", "example", "localhost"}
RESERVED_DOMAINS = {"example.com", "example.org", "example.net"}
# Template / theme filler that sites ship unchanged.
PLACEHOLDER_DOMAINS = {"domain.com", "yourdomain.com", "yoursite.com", "yourcompany.com"}
PLACEHOLDER_LOCALS = {"you", "your", "yourname", "youremail", "name", "username", "email"}
# Regex-scraped "addresses" that are really asset filenames (logo@2x.png).
ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}


def is_placeholder_email(email: str) -> bool:
    local, _, host = (email or "").strip().lower().rpartition("@")
    if not local or not host:
        return True
    tld = host.rsplit(".", 1)[-1]
    if tld in RESERVED_TLDS or tld in ASSET_TLDS:
        return True
    if any(host == d or host.endswith("." + d) for d in RESERVED_DOMAINS | PLACEHOLDER_DOMAINS):
        return True
    return local in PLACEHOLDER_LOCALS


def _name_parts(name: str) -> list[str]:
    return [p for p in re.split(r"[^a-z0-9]+", fold(name)) if len(p) >= 2]


def local_matches_name(local: str, names) -> bool:
    """Does the local-part spell one of `names`? Matches a whole name token
    ("jane.smith", "smith"), or the usual concatenations: janesmith, jsmith,
    janes, smithjane, smithj. Tokens shorter than 3 chars never match alone."""
    folded = fold(local)
    tokens = set(re.split(r"[^a-z]+", folded)) - {""}
    compact = re.sub(r"[^a-z]", "", folded)
    for name in names or ():
        parts = _name_parts(name)
        if any(len(p) >= 3 and p in tokens for p in parts):
            return True
        if len(parts) >= 2:
            # Either order: "Jane Smith" and Companies House's "SMITH, Jane".
            for first, last in ((parts[0], parts[-1]), (parts[-1], parts[0])):
                if compact in {first + last, first[0] + last, first + last[0]}:
                    return True
    return False


def pick_company_email(emails: list, domain: str, known_names=()) -> tuple[str, str, str]:
    """Choose the best company email. Returns (email, email_type, source_url).

    Placeholders are never chosen. Generic inboxes (info@/contact@) are kept --
    legitimate first touch for partnership outreach -- with partnership/BD inboxes
    ranked highest. A mailbox matching a known person outranks all role inboxes.
    On-domain emails are preferred over off-domain ones.
    """
    from opencold.discovery_contact_data import COMPANY_EMAIL_PRIORITY
    from opencold.discovery_data import ROLE_PREFIXES
    from opencold.discovery_domains import normalize_domain

    best: tuple[int, str, str, str] | None = None
    for email, url in emails:
        if "@" not in email or is_placeholder_email(email):
            continue
        local, email_host = email.split("@", 1)
        local = local.lower()
        if local_matches_name(local, known_names):
            rank = 98 if any(sep in local for sep in (".", "_", "-")) else 92
            etype = "person_email"
        else:
            default = 45 if local in ROLE_PREFIXES else 55
            rank, etype = COMPANY_EMAIL_PRIORITY.get(local, default), "role_inbox"
        if normalize_domain(email_host) != domain:
            # Penalize off-domain emails enough that any on-domain inbox wins, but
            # a sole freemail address (common for local SMEs) is still returned.
            rank -= 35
        if best is None or rank > best[0]:
            best = (rank, email, etype, url)
    if not best:
        return "", "", ""
    return best[1], best[2], best[3]
