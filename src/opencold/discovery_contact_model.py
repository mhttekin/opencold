from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Back-end: structured-data-first contact extraction
# ---------------------------------------------------------------------------


@dataclass
class CompanyContacts:
    emails: list = field(default_factory=list)  # list[tuple[email, source_url]]
    phones: list = field(default_factory=list)
    socials: list = field(default_factory=list)
    address: str = ""
    linkedin_company_url: str = ""
    partnership_url: str = ""
    company_name: str = ""


_CONTACT_PATHS = (
    "",
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/imprint",
    "/legal",
    "/company",
)
