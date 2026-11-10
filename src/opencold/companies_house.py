"""UK Companies House Public Data API client (advanced search + enrichment).

A thin stdlib-urllib client, fail-silent like discovery's search backends. Auth
is HTTP Basic with the API key as the username and an EMPTY password.

The key is read (in order) from: COMPANIES_HOUSE_API_KEY (env, populated from
.env), the 'companies_house' provider in config, then the legacy api_key store
-- mirroring discovery._get_serper_key.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 15.0
_UA = "opencold/0.1 (companies-house smearch)"
LIVE_BASE = "https://api.company-information.service.gov.uk"
SANDBOX_BASE = "https://api-sandbox.company-information.service.gov.uk"
_PAGE_SIZE = 100  # CH 'size' per request (max 5000); 100 paginates politely


class CompaniesHouseAuthError(Exception):
    """HTTP 401 from Companies House -- invalid key, or a sandbox/live mismatch.

    Surfaced (not swallowed) so the CLI can tell the user their key was rejected
    rather than reporting a misleading "no companies found".
    """


class CompaniesHouseRequestError(Exception):
    """HTTP 4xx (other than 401) from a Companies House search -- e.g. an
    unsupported company_type / company_status value. Surfaced (not swallowed) so
    a rejected query isn't reported as a misleading "no companies found"."""


def base_url() -> str:
    """Live by default; override with COMPANIES_HOUSE_BASE_URL (or use_sandbox)."""
    return (os.environ.get("COMPANIES_HOUSE_BASE_URL") or LIVE_BASE).rstrip("/")


def use_sandbox() -> None:
    """Point subsequent calls at the sandbox/test base (for test API keys)."""
    os.environ["COMPANIES_HOUSE_BASE_URL"] = SANDBOX_BASE


# SME-friendly legal forms. The advanced-search company_type filter is an
# *include* list, so enumerating the small-business forms is how we exclude plc
# and other large/odd types. Override via --company-type.
DEFAULT_SME_TYPES: tuple[str, ...] = (
    # Verified accepted by the live advanced-search company_type filter. Excludes
    # plc and large/odd forms. Left out on purpose: community-interest-company
    # (API 400) and limited-partnership / a lone "llp" (API 404). "llp" is only
    # accepted alongside another type -- which it always is here.
    "ltd",
    "llp",
    "private-unlimited",
    "private-limited-guarant-nsc",
    "private-limited-guarant-nsc-limited-exemption",
)


def get_companies_house_key() -> str | None:
    """Companies House API key: env (.env) -> provider config -> legacy store."""
    try:
        from opencold import config

        config.load_dotenv()  # no-op if already loaded / no .env
    except Exception:
        pass
    key = os.environ.get("COMPANIES_HOUSE_API_KEY")
    if key:
        return key.strip()
    try:
        from opencold import config

        prov = config.get_provider("companies_house")
        if prov and prov.get("api_key"):
            return prov.get("api_key")
        return config.get_api_key("companies_house")
    except Exception:
        return None


def _auth_header(key: str) -> str:
    """HTTP Basic with the key as username and empty password."""
    token = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _get_json(url: str, api_key: str, *, strict: bool = False) -> dict:
    """GET `url` with Basic auth; return parsed JSON or {} (fail-silent).

    Always raises CompaniesHouseAuthError on 401. When `strict` (the search
    query, where a 4xx means the filters were rejected), also raises
    CompaniesHouseRequestError on other 4xx so the failure isn't hidden as an
    empty result. Enrichment calls stay non-strict: a 404 there (no officers, or
    a missing profile) is a normal empty, not an error.
    """
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": _auth_header(api_key),
            "Accept": "application/json",
            "User-Agent": _UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code == 401:  # don't hide auth failures behind an empty result
            raise CompaniesHouseAuthError(f"HTTP 401 from {base_url()} — key rejected") from e
        if strict and 400 <= e.code < 500:
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                detail = ""
            raise CompaniesHouseRequestError(f"HTTP {e.code} from {base_url()}: {detail}") from e
        return {}
    except Exception:
        return {}


def search_companies(
    sic_codes: list[str],
    *,
    api_key: str,
    limit: int = 50,
    location: str = "",
    company_status: str = "active",
    company_types: tuple[str, ...] | list[str] | None = DEFAULT_SME_TYPES,
    start_index: int = 0,
) -> list[dict]:
    """Advanced search filtered by SIC code(s) (OR-matched) + SME company types.

    Paginates size+start_index until `limit` items or the server runs out of
    hits. `start_index` is the CH offset of the first hit to fetch -- the raw
    pagination cursor that smearch's --page rides on. Any HTTP/parse error stops
    pagination and returns what was gathered so far (the caller handles the empty
    case). Items are raw CH dicts.
    """
    if not sic_codes:
        return []
    base: dict[str, str] = {"sic_codes": ",".join(sic_codes)}
    if company_status:
        base["company_status"] = company_status
    if company_types:
        base["company_type"] = ",".join(company_types)
    if location:
        base["location"] = location

    items: list[dict] = []
    start = max(0, start_index)
    while len(items) < limit:
        page_size = min(_PAGE_SIZE, limit - len(items))
        params = {**base, "size": page_size, "start_index": start}
        url = base_url() + "/advanced-search/companies?" + urllib.parse.urlencode(params)
        data = _get_json(url, api_key, strict=True)
        page = data.get("items") or []
        if not isinstance(page, list) or not page:
            break
        items.extend(page)
        start += len(page)
        total = data.get("hits")
        if isinstance(total, int) and start >= total:
            break
    return items[:limit]


def get_company_profile(number: str, *, api_key: str) -> dict:
    """GET /company/{number} -> profile dict (accounts type, dates...) or {}."""
    if not number:
        return {}
    return _get_json(f"{base_url()}/company/{urllib.parse.quote(number)}", api_key)


def get_company_officers(number: str, *, api_key: str) -> dict:
    """GET /company/{number}/officers -> {active_count, total_results...} or {}.

    Requests a single item: we only need the counts, not the officer list.
    """
    if not number:
        return {}
    return _get_json(
        f"{base_url()}/company/{urllib.parse.quote(number)}/officers?items_per_page=1",
        api_key,
    )


def list_active_officers(number: str, *, api_key: str, limit: int = 35) -> list[dict]:
    """Active (non-resigned) officers as [{"name", "role"}], names as Companies
    House returns them ("SURNAME, Forename"). Resigned officers (those with a
    `resigned_on` date) are dropped."""
    if not number:
        return []
    data = _get_json(
        f"{base_url()}/company/{urllib.parse.quote(number)}/officers?items_per_page={limit}",
        api_key,
    )
    out: list[dict] = []
    for it in data.get("items") or []:
        if it.get("resigned_on"):
            continue
        name = it.get("name") or ""
        if name:
            out.append({"name": name, "role": it.get("officer_role", "")})
    return out
