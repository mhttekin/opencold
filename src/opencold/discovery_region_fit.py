from __future__ import annotations

from opencold import enricher
from opencold import regions_data as rd
from opencold.discovery_contact_model import CompanyContacts
from opencold.discovery_country import _detect_phone_country
from opencold.discovery_domains import (
    normalize_domain,
)
from opencold.discovery_region import (
    _detect_address_country,
    _detect_domain_country,
    _detect_prose_location,
    _resolve_region_key,
    _target_region_tokens,
)
from opencold.discovery_region_data import (
    _AMBIGUOUS,
    _REGION_CCTLD,
    _REGION_PHONE,
)
from opencold.phones import calling_code
from opencold.textnorm import fold

# ---------------------------------------------------------------------------
# Value-add signals: region fit + coarse size tier
# ---------------------------------------------------------------------------


def region_fit(
    contacts: CompanyContacts, website: str, region: str, pages_text: str = ""
) -> tuple[int, str]:
    """Score how strongly a company is anchored in the target region (0-100), and
    flag a region_conflict when it is clearly domiciled elsewhere.

    Anchors (additive): target ccTLD, local phone code, target named in the company's
    own address, or a self-stated HQ. A target mention only in marketing/page text is
    recorded (`page_region_mention`) but scores nothing. When no anchor exists, a
    foreign ccTLD / address country / dialing code / HQ / domain-label adds a
    `region_conflict:<src>` reason (the caller rejects on it). Lets genuine locals
    outrank a multinational's localized page without rejecting locals that export.
    """
    if not (region or "").strip():
        return 0, ""
    region_key = _resolve_region_key(region)
    score = 0
    reasons: list[str] = []
    domain = normalize_domain(website)
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    target_cc = _REGION_CCTLD.get(region_key) if region_key else None
    target_code = _REGION_PHONE.get(region_key) if region_key else None
    phones_joined = "".join(contacts.phones).replace(" ", "")

    if target_cc and (domain.endswith("." + target_cc) or tld == target_cc):
        score += 40
        reasons.append(f"cctld:.{target_cc}")
    if target_code and target_code in {calling_code(p) for p in contacts.phones}:
        score += 35
        reasons.append(f"phone:{target_code}")

    # A target mention in the company's OWN address (or self-stated HQ) anchors it to
    # the region; the same word in marketing/SEO page text does NOT (exporters' pages
    # say "...supplier turkey" constantly), so it scores nothing.
    addr_low = fold(contacts.address)
    pages_low = fold(pages_text)
    tokens = _target_region_tokens(region_key, region)
    addr_anchor = any(t and t in addr_low for t in tokens)
    hq = _detect_prose_location(pages_text)
    if addr_anchor:
        score += 25
        reasons.append("addr_region_match")
    elif hq and hq == region_key:
        score += 20
        reasons.append("hq_region_match")
    elif any(t and t in pages_low for t in tokens):
        reasons.append("page_region_mention")

    # Conflicts only matter when NOTHING anchors the company to the target (score == 0):
    # any genuine target signal (ccTLD / local phone / target address or HQ) is trusted
    # over a foreign mention, so a local that merely lists export markets is never
    # rejected. A foreign ccTLD, stated address country, or dialing code is
    # domicile-grade; a foreign HQ-prose or domain-label name is a weaker last resort.
    conflict = ""
    if region_key and not score:
        for cc in set(_REGION_CCTLD.values()):
            if (
                cc != target_cc
                and cc not in rd.GENERIC_TLDS
                and (tld == cc or domain.endswith("." + cc))
            ):
                conflict = f".{cc}"
                break
        if not conflict:
            ac = _detect_address_country(contacts.address)
            if ac and ac != region_key and ac not in _AMBIGUOUS:
                conflict = f"addr:{ac}"
        if not conflict:
            pc = _detect_phone_country(phones_joined)
            if pc and pc != region_key:
                conflict = f"phone:{pc}"
        if not conflict and hq and hq != region_key and hq not in _AMBIGUOUS:
            conflict = f"hq:{hq}"
        if not conflict:
            dc = _detect_domain_country(domain)
            if dc and dc != region_key:
                conflict = f"domain:{dc}"
    if conflict:
        reasons.append(f"region_conflict:{conflict}")

    return min(score, 100), enricher.FACT_SEPARATOR.join(reasons)
