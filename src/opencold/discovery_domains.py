"""Domain normalization and company-name helpers for discovery."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from opencold.discovery_data import BLOCKED_DOMAINS, BLOCKED_HOST_PARTS, CTA_TEXT, SPACE_RE


def _clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", text or "").strip()


# Second-level labels under a 2-letter ccTLD that are public suffixes, not the
# registrable name (e.g. gov.bd, ac.uk, or.jp). Keeps jbc.gov.bd from collapsing
# to gov.bd. Triggered only when the final label is a 2-letter ccTLD.
_SECOND_LEVEL_TLDS = {
    "co",
    "com",
    "net",
    "org",
    "gov",
    "govt",
    "edu",
    "ac",
    "mil",
    "go",
    "or",
    "ne",
    "gob",
    "gouv",
}


def _registrable_domain(host: str) -> str:
    host = host.lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL_TLDS and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def normalize_domain(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    return _registrable_domain(parsed.netloc or parsed.path)


def _is_blocked_domain(domain: str, source_domain: str = "") -> bool:
    if not domain or domain == source_domain:
        return True
    if domain in BLOCKED_DOMAINS:
        return True
    return any(domain.endswith("." + blocked) for blocked in BLOCKED_DOMAINS)


def _is_blocked_host(host: str) -> bool:
    host = host.lower()
    return any(part in host for part in BLOCKED_HOST_PARTS)


def _company_from_domain(domain: str) -> str:
    stem = domain.split(".")[0]
    return stem.replace("-", " ").replace("_", " ").title()


# B2B marketplaces / directories: they list one company per page but are not a single
# company in any one country. Matched by stem so ccTLD variants (europages.com.tr) also
# hit. Routed to 'review', never 'verified'.
_AGGREGATOR_DOMAINS = {
    "fordaq.com",
    "europages.com",
    "kompass.com",
    "go4worldbusiness.com",
    "globalwood.org",
    "bulurum.com",
    "isdunyasirehberi.net",
    "tradeindia.com",
    "exporthub.com",
    "alibaba.com",
    "made-in-china.com",
    "globalsources.com",
    "indiamart.com",
    "thomasnet.com",
    "ec21.com",
    "tradekey.com",
    "yellowpages.com",
    "telecontact.ma",
    "kerix.net",
    "kerix-export.net",
    "goafricaonline.com",
    "enfrecycling.com",
}
_AGGREGATOR_STEMS = {d.split(".")[0] for d in _AGGREGATOR_DOMAINS}
_AGGREGATOR_RE = re.compile(
    r"\b(?:b2b (?:marketplace|platform)|marketplace for|business directory|"
    r"company directory|trade directory|suppliers? and buyers?|buyers? and suppliers?|"
    r"list of (?:companies|suppliers|manufacturers)|connect(?:s|ing)? (?:buyers|businesses)|"
    # directory phrasing in other languages / translated summaries
    r"directory of (?:professionals|companies|businesses|suppliers|manufacturers)|"
    r"yellow ?pages|pages jaunes|annuaire|directorio de empresas|firmenverzeichnis|"
    r"firma rehberi)\b",
    re.IGNORECASE,
)


def _is_aggregator(domain: str, summary: str = "") -> bool:
    """True for B2B marketplaces/directories (by known stem or summary phrasing)."""
    d = (domain or "").lower()
    if d and d.split(".")[0] in _AGGREGATOR_STEMS:
        return True
    return bool(summary and _AGGREGATOR_RE.search(summary))


def _is_government_domain(domain: str) -> bool:
    """True for government/military sites: .gov/.mil, or gov./govt./go./mil. under a
    ccTLD ("go" is the government second level in .go.jp/.go.ke/.go.ug/.go.id/...)."""
    parts = (domain or "").lower().split(".")
    if len(parts) < 2:
        return False
    if parts[-1] in ("gov", "mil"):
        return True
    return len(parts) >= 3 and parts[-2] in ("gov", "govt", "go", "mil") and len(parts[-1]) == 2


def _company_from_anchor(text: str, domain: str) -> str:
    text = _clean_text(text)
    if CTA_TEXT.match(text):
        return _company_from_domain(domain)
    if 2 <= len(text) <= 60 and not text.lower().startswith(("http", "www.")):
        return text
    return _company_from_domain(domain)
