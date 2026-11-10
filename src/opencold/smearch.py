"""smearch -- find UK SMEs by matching an ICP to SIC codes via Companies House.

TODO(size-preference): we currently target FRESH, SMALL SMEs. Companies House
advanced search has no company-size filter, so "size" is a *ranking* signal here,
not a filter. Each company is scored by:
  - accounts type   (micro / small-exemption filings rank highest)   [strongest]
  - active officers (fewer officers => smaller / simpler company)
  - incorporation recency (younger companies rank higher -- recency is
    deliberately weighted up so fresh SMEs surface first)
Revisit when requirements firm up: make the weights/buckets configurable, add a
true size *filter* (per-company accounts-category gate), and parallelise the
enrichment calls. Tune the SME_* / W_* constants below.

Orchestration lives here; user-facing messaging (genericness warnings, the
API-key gate, dry-run preview) lives in cli.do_smearch so this stays testable.
"""

from __future__ import annotations

import csv
import datetime
from dataclasses import dataclass, field

from opencold import companies_house as ch
from opencold import sic_match

# --- SME-likeness scoring (tunable; see the size-preference TODO above) ------

# Component weights. Recency is boosted relative to a plain tie-breaker to bias
# results toward fresh SMEs, while accounts type stays the strongest signal.
W_ACCOUNT = 2.0
W_OFFICERS = 1.5
W_RECENCY = 1.0

# Companies House accounts type -> size signal (0..3): smaller filings rank up.
_ACCOUNT_SCORE: dict[str, float] = {
    "micro-entity": 3.0,
    "total-exemption-small": 3.0,
    "audit-exemption-subsidiary": 3.0,
    "small": 2.0,
    "total-exemption-full": 2.0,
    "abridged": 2.0,
    "filing-exemption-subsidiary": 2.0,
    "medium": 1.0,
    "full": 0.0,
    "group": 0.0,
    "dormant": 0.5,
}


def _account_score(account_type: str) -> float:
    return _ACCOUNT_SCORE.get((account_type or "").lower(), 1.0)  # unknown: neutral


def _officer_score(active_count) -> float:
    if not isinstance(active_count, int) or active_count <= 0:
        return 1.0  # unknown: neutral
    if active_count <= 2:
        return 3.0
    if active_count <= 5:
        return 2.0
    if active_count <= 10:
        return 1.0
    return 0.0


def _recency_score(inc_year, this_year: int) -> float:
    if not isinstance(inc_year, int) or inc_year <= 0:
        return 1.0  # unknown: neutral
    age = max(0, this_year - inc_year)
    if age <= 2:
        return 3.0
    if age <= 5:
        return 2.0
    if age <= 10:
        return 1.0
    return 0.0


def sme_score(account_type: str, active_count, inc_year, this_year: int) -> float:
    """Higher => stronger fresh/small SME. See the size-preference TODO."""
    return round(
        W_ACCOUNT * _account_score(account_type)
        + W_OFFICERS * _officer_score(active_count)
        + W_RECENCY * _recency_score(inc_year, this_year),
        2,
    )


# --- enrichment -------------------------------------------------------------


@dataclass
class EnrichedCompany:
    item: dict
    account_type: str = ""
    officer_count: int | None = None
    inc_year: int | None = None
    sme: float = 0.0


def _year_of(date_str) -> int | None:
    if isinstance(date_str, str) and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


# Accounts filed as dormant => registered but not trading, useless for outreach.
_DORMANT_ACCOUNT_TYPES = {"dormant"}


def is_dormant(enr: "EnrichedCompany") -> bool:
    return (enr.account_type or "").lower() in _DORMANT_ACCOUNT_TYPES


def enrich_company(item: dict, *, api_key: str, this_year: int) -> EnrichedCompany:
    """Fetch the size signals for one company and compute its SME score."""
    number = item.get("company_number", "") or ""
    profile = ch.get_company_profile(number, api_key=api_key)
    officers = ch.get_company_officers(number, api_key=api_key)

    last_accounts = (profile.get("accounts") or {}).get("last_accounts") or {}
    account_type = last_accounts.get("type", "") or ""
    active = officers.get("active_count")
    if not isinstance(active, int):
        active = officers.get("total_results")
    inc_year = _year_of(item.get("date_of_creation") or profile.get("date_of_creation"))

    return EnrichedCompany(
        item=item,
        account_type=account_type,
        officer_count=active if isinstance(active, int) else None,
        inc_year=inc_year,
        sme=sme_score(account_type, active, inc_year, this_year),
    )


# --- CSV output -------------------------------------------------------------

# sme_score first so the file reads as a ranked list of the strongest SMEs.
# Base columns, then the enrichment columns (kept in sync with
# smearch_enrich.ENRICH_FIELDS; only filled for the enriched top-N rows).
CSV_FIELDS: list[str] = [
    "sme_score",
    "company_name",
    "company_number",
    "company_status",
    "company_type",
    "incorporation_year",
    "date_of_creation",
    "account_type",
    "officer_count",
    "sic_codes",
    "matched_sic_codes",
    "matched_sic_descriptions",
    "matched_icp_terms",
    "address_line_1",
    "address_line_2",
    "locality",
    "region",
    "postal_code",
    "country",
    "company_url",
    "officer_names",
    "website",
    "website_confidence",
    "address_matched",
    "phone",
    "email",
    "email_type",
    "contact_source",
]

_CH_COMPANY_URL = "https://find-and-update.company-information.service.gov.uk/company/"


def company_to_row(enr: EnrichedCompany, matches: list[sic_match.SicMatch]) -> dict:
    """Flatten an enriched company into a CSV row, defensively (.get throughout).

    Records which of the company's own SIC codes overlap the ones we queried,
    plus the union of ICP terms those matched SICs evidence.
    """
    item = enr.item
    addr = item.get("registered_office_address") or {}
    company_sics = item.get("sic_codes") or []
    by_code = {m.code: m for m in matches}
    overlap = [c for c in company_sics if c in by_code]
    descs = [by_code[c].description for c in overlap]
    terms = sorted({t for c in overlap for t in by_code[c].matched_terms})
    num = item.get("company_number", "") or ""
    return {
        "sme_score": enr.sme,
        "company_name": item.get("company_name", "") or "",
        "company_number": num,
        "company_status": item.get("company_status", "") or "",
        "company_type": item.get("company_type", "") or "",
        "incorporation_year": enr.inc_year or "",
        "date_of_creation": item.get("date_of_creation", "") or "",
        "account_type": enr.account_type or "",
        "officer_count": enr.officer_count if enr.officer_count is not None else "",
        "sic_codes": ", ".join(company_sics),
        "matched_sic_codes": ", ".join(overlap),
        "matched_sic_descriptions": " | ".join(descs),
        "matched_icp_terms": ", ".join(terms),
        "address_line_1": addr.get("address_line_1", "") or "",
        "address_line_2": addr.get("address_line_2", "") or "",
        "locality": addr.get("locality", "") or "",
        "region": addr.get("region", "") or "",
        "postal_code": addr.get("postal_code", "") or "",
        "country": addr.get("country", "") or "",
        "company_url": (_CH_COMPANY_URL + num) if num else "",
        # Enrichment columns -- blank here, filled by smearch_enrich for the top-N.
        "officer_names": "",
        "website": "",
        "website_confidence": "",
        "address_matched": "",
        "phone": "",
        "email": "",
        "email_type": "",
        "contact_source": "",
    }


def write_smes_csv(rows: list[dict], output: str) -> None:
    """Write SME rows; extrasaction='ignore' so stray CH keys never crash."""
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# --- orchestration ----------------------------------------------------------


@dataclass
class SmearchResult:
    match: sic_match.MatchResult
    rows: list[dict] = field(default_factory=list)


def plan_matches(
    icp: str,
    *,
    sic_codes: list[str] | None = None,
    roles: list[str] | None = None,
    use_expansion: bool = True,
    use_llm: bool = True,
    provider: dict | None = None,
    max_sics: int = 5,
    min_score: float = 1.0,
) -> sic_match.MatchResult:
    """Resolve the SIC codes to query: explicit --sic override, else expand the
    ICP with synonyms and match it against the SIC list (steered by `roles`)."""
    if sic_codes:
        return sic_match.MatchResult(sic_match.matches_for_codes(sic_codes), "ok", [], roles or [])
    expansion: set[str] = set()
    if use_expansion:
        from opencold import icp_expansion

        expansion = icp_expansion.expand_icp(icp, use_llm=use_llm, provider=provider)
    return sic_match.match_icp_to_sics(
        icp,
        expansion,
        roles=roles,
        max_sics=max_sics,
        min_score=min_score,
    )


# Factory-plausibility by accounts size: small/medium rank above micro, above
# large; unknown/dormant lowest. A real factory is rarely a 1-person micro, but
# we still keep SMEs (no preference for large). Used only for "factory" ranking.
_FACTORY_ACCOUNT_RANK = {
    "small": 3,
    "total-exemption-small": 3,
    "total-exemption-full": 3,
    "abridged": 3,
    "medium": 3,
    "micro-entity": 2,
    "full": 1,
    "group": 1,
}


def _factory_account_score(account_type: str) -> int:
    return _FACTORY_ACCOUNT_RANK.get((account_type or "").lower(), 0)


def _size_matches(account_type: str, size_filter: list[str]) -> bool:
    """True if the accounts type matches any requested size token (substring),
    e.g. 'small' matches 'total-exemption-small'."""
    at = (account_type or "").lower()
    return any(tok.lower() in at for tok in size_filter if tok)


def page_to_start_index(page: int, limit: int) -> int:
    """Map a 1-based --page to a Companies House search offset: page 1 starts at
    0, each page advances by `limit`. The reusable pagination primitive other
    smearch functionality can share (page <-> index). Page <= 1 clamps to 0."""
    return max(0, (max(1, page) - 1) * limit)


# How many pages gather_fresh_pages will walk past fully-seen ones before giving
# up -- a backstop so a heavily-used seen-DB can't spin the search forever.
DEFAULT_MAX_PAGE_WALK = 10


@dataclass
class FreshPages:
    rows: list[dict] = field(default_factory=list)  # fresh (unseen) ranked rows
    pages_walked: int = 0
    skipped_seen: int = 0  # rows dropped because already recorded
    saw_any: bool = False  # did any page return companies at all?


def gather_fresh_pages(
    collect,
    *,
    start_page: int = 1,
    target: int = 10,
    is_seen=None,
    max_pages: int = DEFAULT_MAX_PAGE_WALK,
) -> FreshPages:
    """Walk pages from `start_page` accumulating ranked rows not already seen,
    until `target` fresh rows are gathered or the result set / page budget runs
    out. This is how smearch keeps surfacing *new* companies across runs.

    `collect(page)` returns that page's ranked rows (`[]` once CH is exhausted)
    and owns any user-facing progress messaging. `is_seen(rows)` returns the set
    of already-recorded company numbers to drop; pass None to keep everything --
    the `--no-db` path, which then stops after a single page (old behaviour).
    """
    out = FreshPages()
    page = max(1, start_page)
    while len(out.rows) < target and out.pages_walked < max_pages:
        rows = collect(page)
        out.pages_walked += 1
        if not rows:
            break  # CH ran out of companies
        out.saw_any = True
        if is_seen is None:
            out.rows.extend(rows)
            break  # no dedup -> single page (respects --page; old behaviour)
        seen = is_seen(rows)
        fresh = [r for r in rows if r.get("company_number") not in seen]
        out.skipped_seen += len(rows) - len(fresh)
        out.rows.extend(fresh)
        page += 1
    return out


def collect_smes(
    matches: list[sic_match.SicMatch],
    *,
    api_key: str,
    limit: int = 50,
    location: str = "",
    status: str = "active",
    company_types: tuple[str, ...] | list[str] | None = None,
    this_year: int | None = None,
    progress=None,
    exclude_dormant: bool = True,
    factory: bool = False,
    size_filter: list[str] | None = None,
    start_index: int = 0,
) -> list[dict]:
    """Search Companies House for the matched SICs, enrich each company, drop
    dormant ones (default), and return rows ranked strongest-SME-first.

    Dormant status only shows in the per-company accounts type, not in search, so
    it's filtered after enrichment. We over-fetch the (cheap) search pool and stop
    enriching (2 calls each) once `limit` companies are collected, so dropping
    dormant ones still fills the limit. `factory` reorders by factory-plausible
    accounts size (small/medium first); `size_filter` keeps only matching sizes.
    For factory mode the caller walks this whole pool to backfill. `start_index`
    offsets the underlying CH search -- smearch's --page cursor (see
    `page_to_start_index`).
    """
    if this_year is None:
        this_year = datetime.date.today().year
    pool = limit * 2 if exclude_dormant else limit
    items = ch.search_companies(
        [m.code for m in matches],
        api_key=api_key,
        limit=pool,
        location=location,
        company_status=status,
        company_types=company_types or ch.DEFAULT_SME_TYPES,
        start_index=start_index,
    )
    enriched: list[EnrichedCompany] = []
    for item in items:
        enr = enrich_company(item, api_key=api_key, this_year=this_year)
        if exclude_dormant and is_dormant(enr):
            continue
        if size_filter and not _size_matches(enr.account_type, size_filter):
            continue
        enriched.append(enr)
        if progress:
            progress(len(enriched), limit)
        if len(enriched) >= limit:
            break
    if factory:
        enriched.sort(
            key=lambda e: (
                -_factory_account_score(e.account_type),
                -e.sme,
                e.officer_count if e.officer_count is not None else 999,
                (e.item.get("company_name") or ""),
            )
        )
    else:
        enriched.sort(
            key=lambda e: (
                -e.sme,
                e.officer_count if e.officer_count is not None else 999,
                (e.item.get("company_name") or ""),
            )
        )
    return [company_to_row(e, matches) for e in enriched]


def run_smearch(
    icp: str,
    *,
    output: str = "smes.csv",
    api_key: str | None = None,
    dry_run: bool = False,
    sic_codes: list[str] | None = None,
    roles: list[str] | None = None,
    use_expansion: bool = True,
    use_llm: bool = True,
    provider: dict | None = None,
    max_sics: int = 5,
    min_score: float = 1.0,
    limit: int = 50,
    location: str = "",
    status: str = "active",
    company_types: tuple[str, ...] | list[str] | None = None,
    this_year: int | None = None,
    exclude_dormant: bool = True,
    factory: bool = False,
    size_filter: list[str] | None = None,
    start_index: int = 0,
) -> SmearchResult:
    """Library convenience: plan -> collect -> write. The CLI orchestrates the
    same steps itself so it can interleave user messaging (and the factory walk).
    `start_index` offsets the CH search for pagination (see `page_to_start_index`)."""
    match = plan_matches(
        icp,
        sic_codes=sic_codes,
        roles=roles,
        use_expansion=use_expansion,
        use_llm=use_llm,
        provider=provider,
        max_sics=max_sics,
        min_score=min_score,
    )
    if dry_run or not match.matches or not api_key:
        return SmearchResult(match, [])
    rows = collect_smes(
        match.matches,
        api_key=api_key,
        limit=limit,
        location=location,
        status=status,
        company_types=company_types,
        this_year=this_year,
        exclude_dormant=exclude_dormant,
        factory=factory,
        size_filter=size_filter,
        start_index=start_index,
    )
    if output:
        write_smes_csv(rows, output)
    return SmearchResult(match, rows)
