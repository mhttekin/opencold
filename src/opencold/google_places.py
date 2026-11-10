"""Google Places API (New) client -- find a business by "name, address".

Used as a fallback when web search can't resolve a company's website: returns
the business phone and, if Google has it, a website URI (which we then crawl for
an email). Places never returns email. Fail-silent like the other clients.

Key: GOOGLE_PLACES_API_KEY (env / .env) or the 'google_places' provider config.
"""
from __future__ import annotations

import json
import os
import urllib.request

_URL = "https://places.googleapis.com/v1/places:searchText"
_TIMEOUT = 15.0
# Only request the fields we use -- Places (New) requires an explicit field mask.
_FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.websiteUri,"
    "places.nationalPhoneNumber,places.internationalPhoneNumber,places.id"
)


def get_places_key() -> str | None:
    """Places API key: env (.env) -> provider config -> legacy store."""
    try:
        from opencold import config
        config.load_dotenv()
    except Exception:
        pass
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if key:
        return key.strip()
    try:
        from opencold import config
        prov = config.get_provider("google_places")
        if prov and prov.get("api_key"):
            return prov.get("api_key")
        return config.get_api_key("google_places")
    except Exception:
        return None


def find_place(query: str, *, api_key: str) -> dict | None:
    """Top text-search match for `query` (e.g. "Acme Ltd, 1 High St, London").

    Returns {name, address, website, phone, id} or None (no match / error).
    """
    if not query or not api_key:
        return None
    body = json.dumps({"textQuery": query}).encode("utf-8")
    req = urllib.request.Request(_URL, data=body, headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _FIELD_MASK,
    })
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None
    places = data.get("places") or []
    if not places:
        return None
    p = places[0]
    return {
        "name": (p.get("displayName") or {}).get("text", ""),
        "address": p.get("formattedAddress", ""),
        "website": p.get("websiteUri", ""),
        "phone": p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber") or "",
        "id": p.get("id", ""),
    }
