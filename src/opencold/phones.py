"""Phone validation and E.164 normalization (via the `phonenumbers` library).

A number is accepted only if phonenumbers says it is a valid number. Local formats
("05333932020") need a region hint (ISO 3166 alpha-2, e.g. "TR"), taken from the
company's ccTLD or its target country; without one, only "+"-prefixed numbers parse.
"""

from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

# ccTLDs whose ISO 3166 code differs from the TLD.
_CCTLD_TO_ISO = {"uk": "GB"}


def iso_region(cc: str | None) -> str | None:
    """ccTLD / ISO code ("tr", "uk", "GB") -> a region phonenumbers supports, or None."""
    code = _CCTLD_TO_ISO.get((cc or "").lower(), (cc or "").upper())
    return code if code in phonenumbers.SUPPORTED_REGIONS else None


def region_hint(website: str = "", fallback_cc: str | None = None) -> str | None:
    """Region to parse local numbers with: the site's ccTLD, else `fallback_cc`
    (e.g. the target country's ccTLD), else None."""
    host = (website or "").lower().split("://")[-1].split("/")[0].split(":")[0]
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    return iso_region(tld) or iso_region(fallback_cc)


def normalize_phone(raw: str, region: str | None = None) -> str:
    """E.164 ("+905333932020") if `raw` is a valid number, else ""."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        num = phonenumbers.parse(raw, iso_region(region))
    except NumberParseException:
        return ""
    if not phonenumbers.is_valid_number(num):
        return ""
    return phonenumbers.format_number(num, PhoneNumberFormat.E164)


def calling_code(e164: str) -> str:
    """ "+90" for "+905333932020"; "" if it isn't a parseable +number."""
    try:
        return f"+{phonenumbers.parse(e164, None).country_code}"
    except NumberParseException:
        return ""
