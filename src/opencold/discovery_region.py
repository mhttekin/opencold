from __future__ import annotations

import re

from opencold.discovery_region_data import (
    _AMBIGUOUS,
    _COUNTRY_DEMONYMS,
    _COUNTRY_DEMONYMS_BY_LEN,
    _COUNTRY_NAMES,
    _COUNTRY_NAMES_BY_LEN,
    _REGION_ALIASES,
    _REGION_CITIES,
    _REGION_LANGS,
)
from opencold.textnorm import fold


def _resolve_region_key(region: str) -> str | None:
    """Map a freeform region string to a canonical key (longest alias wins)."""
    r = fold(region)
    for alias in sorted(_REGION_ALIASES, key=len, reverse=True):
        if len(alias) <= 3:
            if re.search(r"\b" + re.escape(alias) + r"\b", r):
                return _REGION_ALIASES[alias]
        elif alias in r:
            return _REGION_ALIASES[alias]
    return None


# Cap the number of business languages a single region is searched in, so a
# many-language market (e.g. switzerland: de/fr/it) doesn't explode the query count.
# Matching still uses every language; only SEARCH is capped. Most regions have ≤2.
MAX_SEARCH_LANGS = 3


def _region_languages(region: str) -> list[str]:
    """Business-web languages to ALSO search/translate into for `region` (most-
    productive first), or [] where English is the de-facto business language. Derived
    from regions_data.COUNTRIES; multilingual markets (morocco -> ["fr","ar"]) return
    several. Foreign same-language companies are dropped later by region_fit."""
    return list(_REGION_LANGS.get(_resolve_region_key(region) or "", []))


def _region_language(region: str) -> str | None:
    """Primary local language for `region` (first of _region_languages), or None to
    stay English. Kept for single-language callers and the status line."""
    langs = _region_languages(region)
    return langs[0] if langs else None


def _target_region_tokens(region_key: str | None, region: str) -> list[str]:
    """Anchor vocabulary for the TARGET region: canonical key + its longer aliases +
    known cities. Used to decide whether the target is actually named in an address."""
    if not region_key:
        r = fold(region).strip()
        return [r] if r else []
    toks = {region_key}
    toks.update(a for a, k in _REGION_ALIASES.items() if k == region_key and len(a) > 3)
    toks.update(_REGION_CITIES.get(region_key, []))
    return [t for t in toks if t]


def _resolve_place(place: str) -> str | None:
    """Resolve a free-text place (country name/variant, demonym, or city) to a
    canonical region key, or None."""
    p = fold(place).strip()
    if not p:
        return None
    for name in _COUNTRY_NAMES_BY_LEN:
        if re.search(r"\b" + re.escape(name) + r"\b", p):
            return _COUNTRY_NAMES[name]
    for dem in _COUNTRY_DEMONYMS_BY_LEN:
        if re.search(r"\b" + re.escape(dem) + r"\b", p):
            return _COUNTRY_DEMONYMS[dem]
    for rk, cities in _REGION_CITIES.items():
        if any(re.search(r"\b" + re.escape(c) + r"\b", p) for c in cities):
            return rk
    return None


def _detect_address_country(text: str) -> str | None:
    """Detect the country a free-form ADDRESS declares (its stated domicile).

    Prefers an unambiguous country when several names appear, so "Atlanta, Georgia,
    USA" resolves to united states rather than Georgia-the-country."""
    if not text:
        return None
    low = fold(text)
    found: list[str] = []
    for name in _COUNTRY_NAMES_BY_LEN:
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            found.append(_COUNTRY_NAMES[name])
    for dem in _COUNTRY_DEMONYMS_BY_LEN:
        if re.search(r"\b" + re.escape(dem) + r"(?:-based)?\b", low):
            found.append(_COUNTRY_DEMONYMS[dem])
    if not found:
        return None
    unambiguous = [f for f in found if f not in _AMBIGUOUS]
    return unambiguous[0] if unambiguous else found[0]


# HQ-statement idioms: "based/headquartered/registered in <place>" (verb form captures
# the place after "in", stopping at a comma) and "<place>-based" (adjective form).
_HQ_PLACE = r"([^\W\d_][^\d\n,;:|]{1,38})"
_HQ_VERB_RE = re.compile(
    r"\b(?:based|headquarter(?:ed|s)?|head\s*offices?|hq|registered|incorporated)\s+in\s+"
    + _HQ_PLACE,
    re.IGNORECASE,
)
_HQ_ADJ_RE = re.compile(r"\b([^\W\d_][^\d\n,;:|]{0,28}?)[ \-]based\b", re.IGNORECASE)
# A market/customer subject immediately before an HQ idiom means the place is where the
# company SELLS, not where it IS ("serving customers based in Turkey"). Self-referential
# singulars ("our company based in X") are deliberately NOT listed, only market plurals.
_HQ_CUSTOMER_RE = re.compile(
    r"\b(?:customers?|clients?|buyers?|partners?|distributors?|importers?|resellers?|"
    r"companies|businesses|firms|manufacturers|suppliers|organi[sz]ations|enterprises|brands)\W*$",
    re.IGNORECASE,
)


def _detect_prose_location(text: str) -> str | None:
    """Detect a company's self-stated HQ from prose, ignoring market/customer subjects.
    Returns a canonical region key or None."""
    if not text:
        return None
    low = fold(text)
    for rx in (_HQ_VERB_RE, _HQ_ADJ_RE):
        for m in rx.finditer(low):
            if _HQ_CUSTOMER_RE.search(low[max(0, m.start() - 45) : m.start()]):
                continue
            rk = _resolve_place(m.group(1))
            if rk:
                return rk
    return None


def _detect_domain_country(domain: str) -> str | None:
    """Detect an UNAMBIGUOUS country named in the registrable domain LABEL (never the
    URL path). Matches names >=5 chars as a prefix/suffix/hyphen-segment, so 'oman'
    inside 'romania' or a brand like 'jordan' never fires."""
    label = fold(domain.split(".")[0] if domain else "")
    if not label:
        return None
    segments = set(re.split(r"[^a-zà-ÿ]+", label))
    for name in _COUNTRY_NAMES_BY_LEN:
        rk = _COUNTRY_NAMES[name]
        if rk in _AMBIGUOUS:
            continue
        n = name.replace(" ", "")
        if len(n) < 5:
            continue
        if n in segments or label.startswith(n) or label.endswith(n):
            return rk
    return None
