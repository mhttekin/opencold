from __future__ import annotations

from opencold import regions_data as rd
from opencold.discovery_contact_model import CompanyContacts
from opencold.discovery_domains import (
    normalize_domain,
)
from opencold.discovery_region import (
    _detect_address_country,
    _detect_domain_country,
    _detect_prose_location,
)
from opencold.discovery_region_data import (
    _PHONE_CC,
    _REGION_CCTLD,
)


def _detect_phone_country(phones_joined: str) -> str | None:
    """Map a leading E.164 calling code to a canonical region key (longest prefix
    wins, so +1 and +880 disambiguate correctly), or None."""
    p = (phones_joined or "").replace(" ", "")
    if not p.startswith("+"):
        return None
    for code in sorted(_PHONE_CC, key=len, reverse=True):
        if p.startswith(code):
            return _PHONE_CC[code]
    return None


def _detected_country(contacts: CompanyContacts, website: str, summary: str = "") -> str:
    """Best-effort detected country for the `country` column, in trust order:
    stated address > phone code > ccTLD > HQ prose > domain label. "" if unknown."""
    by_addr = _detect_address_country(contacts.address)
    if by_addr:
        return by_addr
    by_phone = _detect_phone_country("".join(contacts.phones).replace(" ", ""))
    if by_phone:
        return by_phone
    domain = normalize_domain(website)
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    for name, cc in _REGION_CCTLD.items():
        if cc not in rd.GENERIC_TLDS and (tld == cc or domain.endswith("." + cc)):
            return name
    by_hq = _detect_prose_location(summary)
    if by_hq:
        return by_hq
    return _detect_domain_country(domain) or ""
