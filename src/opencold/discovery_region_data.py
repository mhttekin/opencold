"""Derived region lookup tables shared by discovery helpers."""

from opencold import regions_data as rd
from opencold.textnorm import fold

# Region hint maps — keyed by a CANONICAL region name. Freeform user input
# ("United Kingdom (UK)", "uk", "England") is resolved to a canonical key via
# _resolve_region_key before lookup, so the signals actually fire regardless of
# how the region was phrased. Easily extensible.
# Region lookup tables are DERIVED from regions_data.COUNTRIES (the single source of
# truth) so widening coverage means editing one file. Names are kept stable for the
# rest of this module.
_REGION_CCTLD = {k: v["cctld"] for k, v in rd.COUNTRIES.items() if v.get("cctld")}
_REGION_PHONE = {k: v["phone"] for k, v in rd.COUNTRIES.items() if v.get("phone")}
_REGION_CITIES = {
    k: [fold(c) for c in v["cities"]] for k, v in rd.COUNTRIES.items() if v.get("cities")
}
_REGION_LANGS = {k: v["langs"] for k, v in rd.COUNTRIES.items() if v.get("langs")}

# Freeform aliases -> canonical region key. Short aliases (<=3 chars) are matched
# on word boundaries; longer ones as substrings (longest first). See _resolve_region_key.
_REGION_ALIASES = {fold(a): k for k, v in rd.COUNTRIES.items() for a in v["aliases"]}

# Foreign-country detection tables. _COUNTRY_NAMES maps any name/variant to its
# canonical key; _COUNTRY_DEMONYMS maps adjectives ("british"); _AMBIGUOUS holds keys
# whose NAME doubles as a common word / US place (never trigger a reject, excluded from
# domain matching). _PHONE_CC maps an E.164 calling code to a country (first listed
# owner wins for shared codes; +1/+7 pinned to the dominant economy).
_COUNTRY_NAMES = dict(_REGION_ALIASES)
_COUNTRY_DEMONYMS = {fold(d): k for k, v in rd.COUNTRIES.items() for d in v.get("demonyms", [])}
_AMBIGUOUS = {k for k, v in rd.COUNTRIES.items() if v.get("ambiguous")}


def _build_phone_cc() -> dict:
    out: dict[str, str] = {}
    for key, val in rd.COUNTRIES.items():
        code = val.get("phone")
        if code and code not in out:
            out[code] = key
    out["+1"] = "united states"
    out["+7"] = "russia"
    return out


_PHONE_CC = _build_phone_cc()
_COUNTRY_NAMES_BY_LEN = sorted(_COUNTRY_NAMES, key=len, reverse=True)
_COUNTRY_DEMONYMS_BY_LEN = sorted(_COUNTRY_DEMONYMS, key=len, reverse=True)
