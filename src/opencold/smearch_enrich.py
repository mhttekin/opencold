"""Top-N enrichment for smearch rows.

For each (top-ranked) company it adds, reusing the discover command's stack:
  1. Active officer names (from Companies House -- resigned ones dropped).
  2. The company website via web search (name + address; falling back to
     name-only at lower confidence), then on-site phone/email and a check that
     the registered-office address actually appears on the site.
  3. A Google Places fallback when no website is found (phone, and a website URI
     to crawl for an email).

For "factory" intent, enrichment walks DOWN the ranked pool and keeps only
companies whose website content (or registered address) shows real production /
facility evidence -- backfilling until N factories are found (see
enrich_top_factories / is_factory_company).

Web search auto-uses Serper when a key is present and the LLM is optional --
exactly like discovery. Only the top N rows are enriched (expensive per row).
"""

from __future__ import annotations

import re

from opencold import companies_house as ch
from opencold import discovery, google_places

_REGION = "United Kingdom"

# Enrichment columns added to every smearch row (empty until enriched).
ENRICH_FIELDS = [
    "officer_names",
    "website",
    "website_confidence",
    "address_matched",
    "phone",
    "email",
    "email_type",
    "contact_source",
]


def blank_fields() -> dict:
    return {k: "" for k in ENRICH_FIELDS}


def _format_officer_name(ch_name: str) -> str:
    """'SURNAME, Forename Middle' -> 'Forename Middle Surname' (title-cased)."""
    if "," in ch_name:
        surname, rest = ch_name.split(",", 1)
        full = f"{rest.strip()} {surname.strip()}"
    else:
        full = ch_name.strip()
    return full.title()


def _address_str(row: dict) -> str:
    parts = [
        row.get("address_line_1", ""),
        row.get("address_line_2", ""),
        row.get("locality", ""),
        row.get("postal_code", ""),
    ]
    return ", ".join(p for p in parts if p)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _address_on_site(row: dict, pages_text: str) -> str:
    """Did the registered-office address show up on the site? Postcode is the
    strongest signal; locality is a weaker fallback."""
    pt = _norm(pages_text)
    pc = _norm(row.get("postal_code", ""))
    if pc and len(pc) >= 5 and pc in pt:
        return "postcode"
    loc = _norm(row.get("locality", ""))
    if loc and len(loc) >= 4 and loc in pt:
        return "locality"
    return ""


def _resolve_website(name: str, locality: str) -> tuple[str, str]:
    """(url, confidence). Try name + location first (high confidence), then
    name-only (low). require_match avoids attaching the wrong company's site."""
    ctx = f"{locality} {_REGION}".strip()
    url = discovery.resolve_company_website(name, context=ctx, prefer_cc="uk", require_match=True)
    if url:
        return url, "name+address"
    url = discovery.resolve_company_website(name, prefer_cc="uk", require_match=True)
    if url:
        return url, "name-only"
    return "", ""


def _site_contacts(website: str, pages: int, names=()) -> tuple[str, str, str]:
    """(phone, email, email_type) extracted from the site via discovery."""
    contacts = discovery.extract_company_contacts(website, max_pages=pages, region_cc="uk")
    phone = contacts.phones[0] if contacts.phones else ""
    if contacts.emails:
        email, etype, _ = discovery.pick_company_email(
            contacts.emails, discovery.normalize_domain(website), names
        )
    else:
        email, etype = "", ""
    return phone, email, etype


def _pages_text(website: str, pages: int) -> str:
    try:
        return " ".join(
            p.text or "" for p in discovery.crawl_company_pages(website, max_pages=pages)
        )
    except Exception:
        return ""


def _llm_confirms_website(
    provider: dict, company: str, address: str, website: str, page_text: str
) -> bool | None:
    """Grounded yes/no: is this website really `company`'s? None on error."""
    try:
        from opencold import generator

        out = generator.complete(
            provider,
            "You verify whether a website belongs to a specific UK company. Reply only YES or NO.",
            f"Company: {company}\nRegistered address: {address}\nWebsite: {website}\n"
            f"Page text (excerpt):\n{page_text[:1500]}\n\nIs this the company's official website?",
            max_tokens=4,
        )
        return out.strip().upper().startswith("Y")
    except Exception:
        return None


# --- factory classification (website content + registered address) ----------
# Phrases on a site that signal a real production operation (vs an artisan maker
# or shop). Matched case-insensitively as substrings of the crawled page text.
_FACTORY_TERMS = (
    "manufacturing facility",
    "production facility",
    "processing facility",
    "our facility",
    "production line",
    "production capacity",
    "manufacturing process",
    "our factory",
    "the factory",
    "factory",
    "warehouse",
    "industrial unit",
    "manufacturing plant",
    "processing plant",
    "production plant",
    "contract manufactur",
    "private label",
    "own label",
    "own-label",
    "oem",
    "bulk supply",
    "bulk order",
    "wholesale supply",
    "trade enquiries",
    "trade customers",
    "units per",
    "tonnes",
    "per annum",
    "sq ft",
    "square feet",
    "production team",
    "manufactured in",
    "produced in our",
)
# Industrial-premises markers in a registered address (cheap CH signal; used when
# the website is weak or absent).
_INDUSTRIAL_ADDRESS_TERMS = (
    "industrial estate",
    "trading estate",
    "business park",
    "industrial park",
    "enterprise park",
    "industrial unit",
    "trade park",
    "trade centre",
    "distribution park",
    "industrial centre",
)


def _factory_keywords(pages_text: str) -> bool:
    low = (pages_text or "").lower()
    return any(term in low for term in _FACTORY_TERMS)


def _industrial_address(row: dict) -> bool:
    addr = " ".join(
        str(row.get(k, "")) for k in ("address_line_1", "address_line_2", "locality")
    ).lower()
    return any(term in addr for term in _INDUSTRIAL_ADDRESS_TERMS)


def _llm_is_factory(provider: dict, company: str, pages_text: str) -> bool | None:
    """Grounded: is this an industrial factory (vs artisan/retail)? None on error."""
    try:
        from opencold import generator

        out = generator.complete(
            provider,
            "Classify a UK company from its website text. Reply only FACTORY or OTHER. "
            "FACTORY = an industrial producer / manufacturing plant / processing facility "
            "(production lines, bulk, wholesale, OEM, private-label). OTHER = artisan/boutique "
            "maker, shop, deli, butcher, market stall, cafe/restaurant, or non-producer.",
            f"Company: {company}\nWebsite text (excerpt):\n{pages_text[:2000]}\n\nFACTORY or OTHER?",
            max_tokens=4,
        )
        return out.strip().upper().startswith("F")
    except Exception:
        return None


def is_factory_company(
    row: dict, pages_text: str, *, use_llm: bool = False, provider: dict | None = None
) -> bool:
    """Is this company a real factory? An industrial-estate registered address is a
    strong yes; otherwise judge website content (LLM when available, else keyword
    evidence). No content and no industrial address => no (so it's skipped)."""
    if _industrial_address(row):
        return True
    if pages_text:
        if use_llm and provider:
            verdict = _llm_is_factory(provider, row.get("company_name", ""), pages_text)
            if verdict is not None:
                return verdict
        return _factory_keywords(pages_text)
    return False


def _finish_enrich(
    row: dict,
    website: str,
    conf: str,
    text: str,
    *,
    ch_key: str,
    use_llm: bool = False,
    provider: dict | None = None,
    places_key: str | None = None,
    pages: int = 4,
) -> dict:
    """Fill a row's enrichment fields given an already-resolved website + crawled
    page text (so the factory gate can reuse the same crawl)."""
    row.update(blank_fields())
    name = row.get("company_name", "")
    number = row.get("company_number", "")
    address = _address_str(row)

    officers = ch.list_active_officers(number, api_key=ch_key) if number else []
    row["officer_names"] = "; ".join(_format_officer_name(o["name"]) for o in officers)
    names = [o["name"] for o in officers]  # person_email only if it names an officer

    if website:
        phone, email, etype = _site_contacts(website, pages, names)
        matched = _address_on_site(row, text)
        # Address not on site => namesake risk; let the LLM confirm/reject when on.
        if use_llm and provider and not matched:
            verdict = _llm_confirms_website(provider, name, address, website, text)
            if verdict is False:
                website = conf = phone = email = etype = matched = ""
            elif verdict is True:
                conf = f"{conf}+llm"
        if website:
            row["contact_source"] = "website"
            row["phone"], row["email"], row["email_type"] = phone, email, etype
            row["address_matched"] = matched

    if not website and places_key:
        place = google_places.find_place(f"{name}, {address}", api_key=places_key)
        if place:
            row["phone"] = place.get("phone", "")
            row["contact_source"] = "google_places"
            if place.get("website"):
                website, conf = place["website"], "google_places"
                _p, row["email"], row["email_type"] = _site_contacts(website, pages, names)
                row["phone"] = row["phone"] or _p
                row["address_matched"] = _address_on_site(row, _pages_text(website, pages))
                row["contact_source"] = "google_places+website"

    row["website"], row["website_confidence"] = website, conf
    return row


def enrich_row(
    row: dict,
    *,
    ch_key: str,
    use_llm: bool = False,
    provider: dict | None = None,
    places_key: str | None = None,
    pages: int = 4,
) -> dict:
    """Enrich one smearch row in place (fail-soft on any single sub-step)."""
    website, conf = _resolve_website(row.get("company_name", ""), row.get("locality", ""))
    text = _pages_text(website, pages) if website else ""
    return _finish_enrich(
        row,
        website,
        conf,
        text,
        ch_key=ch_key,
        use_llm=use_llm,
        provider=provider,
        places_key=places_key,
        pages=pages,
    )


def enrich_rows(
    rows: list[dict],
    *,
    ch_key: str,
    use_llm: bool = False,
    provider: dict | None = None,
    places_key: str | None = None,
    pages: int = 4,
    progress=None,
) -> list[dict]:
    """Enrich each row (the top-N). A failing row is left with blank enrichment
    fields rather than aborting the batch."""
    for i, row in enumerate(rows, 1):
        if progress:
            progress(i, len(rows), row.get("company_name", ""))
        try:
            enrich_row(
                row,
                ch_key=ch_key,
                use_llm=use_llm,
                provider=provider,
                places_key=places_key,
                pages=pages,
            )
        except Exception:
            row.setdefault("officer_names", "")
            for k in ENRICH_FIELDS:
                row.setdefault(k, "")
    return rows


def enrich_top_factories(
    pool: list[dict],
    *,
    target: int,
    ch_key: str,
    use_llm: bool = False,
    provider: dict | None = None,
    places_key: str | None = None,
    pages: int = 4,
    progress=None,
) -> tuple[list[dict], int]:
    """Walk the ranked pool keeping only companies with factory evidence (website
    content or industrial address), until `target` are collected or the pool is
    exhausted. The gate crawls page text once and only the kept rows pay the full
    contact crawl. Returns (kept_rows, scanned_count)."""
    kept: list[dict] = []
    scanned = 0
    for row in pool:
        if len(kept) >= target:
            break
        scanned += 1
        if progress:
            progress(len(kept), target, row.get("company_name", ""))
        try:
            website, conf = _resolve_website(row.get("company_name", ""), row.get("locality", ""))
            text = _pages_text(website, pages) if website else ""
            if not is_factory_company(row, text, use_llm=use_llm, provider=provider):
                continue
            _finish_enrich(
                row,
                website,
                conf,
                text,
                ch_key=ch_key,
                use_llm=use_llm,
                provider=provider,
                places_key=places_key,
                pages=pages,
            )
            kept.append(row)
        except Exception:
            continue
    return kept, scanned
